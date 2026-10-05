#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TABULA-Ω host bridge
====================
Serves the projected desk page, and turns what happens on the desk into real input for this computer:

  keys · text · mouse · OS multi-touch · media keys · window control · live window streaming (PORTAL)
  focused-app detection → context palettes · clipboard history · allow-listed launch/run · OBS WebSocket v5
  OSC / TUIO in+out · MIDI out · local-first VLM/OCR (Ollama → OpenAI-compatible → Anthropic → Tesseract)
  depth-camera touch engine (Wilson band + DIRECT-style fingertips) · IR light plane · ArUco tangibles
  Gray-code camera calibration driven through the page · telemetry (psutil, nvidia-smi, Ollama /api/ps)

Safety: binds 127.0.0.1; a fresh per-run token that only reaches the browser the host opens (URL fragment,
never inlined in the page); Origin + Host allow-lists (DNS-rebinding guard, also in LAN mode); no framing;
starts DISARMED; arming needs the page's TRIBUNAL report (advisory — the host cannot verify a page's critics)
and binds input to the arming window; PANIC is handled out of band and aborts typing mid-string; auto-disarm
on idle/disconnect/flat palm; rate limits; stuck-button and stuck-touch watchdogs; redacted JSONL audit log
in a 0700 directory; argv allow-lists (never a shell; interpreters with inline code are refused).

  pip install websockets numpy opencv-contrib-python psutil mss pillow
  python tabula_host.py [--dry-run] [--sense synthetic|realsense|orbbec|k4a|freenect2|lightplane:N] [--help]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import copy
import email.utils
import glob
import hashlib
import hmac
import http
import io
import json
import logging
import math
import os
import platform
import queue
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

VERSION = "1.0.0"
log = logging.getLogger("tabula")


def _opt(name: str):
    try:
        return __import__(name)
    except Exception:
        return None


np = _opt("numpy")
cv2 = _opt("cv2")
psutil = _opt("psutil")
mss_mod = _opt("mss")
pyperclip = _opt("pyperclip")
try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None
try:
    import websockets  # type: ignore
    from websockets.asyncio.server import serve as ws_serve  # websockets ≥ 13
    from websockets.datastructures import Headers
    from websockets.http11 import Response
except Exception:  # pragma: no cover
    websockets = None

OS = {"win32": "win", "darwin": "mac"}.get(sys.platform, "linux")
HOME = Path(os.environ.get("TABULA_HOME", Path.home() / ".tabula"))
HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------------------
def _win_find(*patterns):
    """newest match of %VAR%-expanded glob patterns (Windows installs that are not on PATH)"""
    for pat in patterns:
        hits = sorted(glob.glob(os.path.expandvars(pat)))
        if hits:
            return hits[-1]
    return None


def _launch_defaults() -> dict:
    if OS != "win":
        return {"code": ["code"], "blender": ["blender"], "obs": ["obs"], "terminal": _terminal_argv()}
    d = {"terminal": _terminal_argv()}
    code = shutil.which("code") or _win_find(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe", r"%ProgramFiles%\Microsoft VS Code\Code.exe")
    d["code"] = [code or "code"]
    blender = shutil.which("blender") or _win_find(r"%ProgramFiles%\Blender Foundation\Blender*\blender.exe")
    d["blender"] = [blender or "blender"]
    obs = _win_find(r"%ProgramFiles%\obs-studio\bin\64bit\obs64.exe")
    d["obs"] = {"argv": [obs], "cwd": os.path.dirname(obs)} if obs else ["obs64.exe"]   # OBS must start in its bin directory
    return d


def _terminal_argv() -> list:
    if OS == "win":
        return ["wt.exe"] if shutil.which("wt.exe") else ["cmd.exe"]
    if OS == "mac":
        return ["open", "-a", "Terminal"]
    for t in ("gnome-terminal", "konsole", "kitty", "alacritty", "wezterm", "xterm"):
        if shutil.which(t):
            return [t]
    return ["xterm"]


def default_config() -> dict:
    return {
        "bind": "127.0.0.1", "port": 7777, "lan": False,
        "extra_origins": [],                 # e.g. "http://desk-pc.lan:7777" — exact origins allowed besides the host's own
        "extra_hosts": [],                   # LAN mode: extra Host names that may reach the page (IPs/hostname of this PC are automatic)
        "allow_no_origin": False,            # accept WebSocket clients that send no Origin (scripts); browsers always send one
        "allow_file_origin": False,          # tabula.html opened from disk (Origin: null is shared by every local file) — opt in
        "observe_disarmed": True,            # PORTAL / clipboard history / scan while disarmed (they never change anything)
        "clip_watch": True,                  # clipboard history; concealed (password-manager) copies are always skipped
        "idle_disarm_s": 900, "hold_timeout_s": 15, "touch_timeout_s": 3,
        "deadman_s": 10,                     # disarm when the arming window stops answering (frozen / hidden tab, lost Wi-Fi)
        "rate": {"act": 40, "midi": 400, "ptr": 500, "touch": 500, "win": 20, "vlm": 2, "scan": 2, "cfg": 5},
        "limits": {"chords": 32, "text": 4000, "paste": 200000, "wheel": 40},
        "punctuation": "physical",          # 'physical' = US key positions (app default bindings) | 'char' = current layout
        "type_via": "auto",                  # auto | keys | paste — 'auto' pastes whatever the backend cannot type layout-safely
        "keyboard_layout": "auto",           # uinput only: 'us' lets it type ASCII as keystrokes; anything else pastes
        "launch": _launch_defaults(),
        "run": {
            "ollama_ps": {"argv": ["ollama", "ps"], "timeout": 8},
            "nvidia_smi": {"argv": ["nvidia-smi"], "timeout": 8},
            "git_status": {"argv": ["git", "status", "--short", "--branch"], "cwd": "~", "timeout": 8},
        },
        "url_schemes": ["http", "https"],
        "http": {},                          # named HTTP actions, e.g. Home Assistant (see README)
        "osc_targets": {"touchdesigner": ["127.0.0.1", 7000], "resolume": ["127.0.0.1", 7001]},
        "tuio_out": None,                    # ["127.0.0.1", 3333]
        "midi_port": "TABULA",
        "obs": {"url": "ws://127.0.0.1:4455", "password": ""},
        "vlm": {"chain": ["ollama", "openai", "anthropic", "tesseract"], "ollama_url": "http://127.0.0.1:11434", "model": "qwen2.5vl:7b",
                "openai_url": "http://127.0.0.1:8080/v1", "openai_model": "", "anthropic_model": "claude-sonnet-5-5", "allow_cloud": False, "timeout": 120},
        "sense": {"band_lo": None, "band_hi": None, "arm_mm": 45.0, "hover_mm": 60.0, "head_mm": 350.0, "min_blob_px": 25, "tip_sep_mm": 22.0,
                  "max_jump_mm": 45.0, "down_frames": 2, "up_frames": 2, "palm_area_mm2": 5500.0, "stun_s": 4.0, "downsample": 2,
                  "euro": {"min_cutoff": 1.2, "beta": 0.02, "d_cutoff": 1.0}, "lightplane_thresh": 200},
        "calib": {"H_desk_raw": None, "raw_source": None, "H_desk_cam": None},
        "tokens_corner_ids": [0, 1, 2, 3],
        "persist_frames": False,
    }


def write_private(path: Path, text: str):
    """atomic write, owner-only (0600) — config, token, page state"""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def redact(v):
    """what the audit log keeps of typed/pasted text: its length and a short hash, never the text"""
    s = str(v)
    return f"<{len(s)} chars · sha256 {hashlib.sha256(s.encode('utf-8', 'replace')).hexdigest()[:10]}>"


class Store:
    """~/.tabula (0700): config.json, token, audit.log, page-state.json, models/ — all 0600"""

    def __init__(self, home: Path):
        self.home = home
        fresh = not home.exists()
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if fresh or home == HOME:
            try:
                os.chmod(home, 0o700)                          # the audit log and page state are nobody else's business
            except OSError:
                pass
        (home / "models").mkdir(exist_ok=True)
        self.cfg_path = home / "config.json"
        self.cfg = default_config()
        self._cli: dict = {}                                    # command-line overrides: live for this run, never saved
        if self.cfg_path.exists():
            try:
                self._merge(self.cfg, json.loads(self.cfg_path.read_text()))
            except Exception as e:
                log.warning("config.json unreadable (%s) — using defaults", e)
        else:
            self.save()
        self.token = secrets.token_urlsafe(32)          # fresh every run: a stolen token dies with the process
        try:
            write_private(home / "token", self.token)
        except Exception:
            pass
        for f in ("config.json", "audit.log", "audit.log.1", "page-state.json"):
            try:
                if (home / f).exists():
                    os.chmod(home / f, 0o600)
            except OSError:
                pass
        self._audit_lock = threading.Lock()

    def override(self, key: str, value):
        """set a key for this run only (CLI flags such as --lan / --port must never end up in config.json)"""
        if key not in self._cli:
            self._cli[key] = copy.deepcopy(self.cfg.get(key))
        self.cfg[key] = value

    @staticmethod
    def _merge(dst: dict, src: dict):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                Store._merge(dst[k], v)
            else:
                dst[k] = v

    def save(self):
        try:
            data = copy.deepcopy(self.cfg)
            for k, v in self._cli.items():                      # persist what the file said, not the CLI flag
                data[k] = v
            write_private(self.cfg_path, json.dumps(data, indent=2))
        except Exception as e:
            log.warning("cannot save config: %s", e)

    def audit(self, kind: str, **kw):
        rec = {"t": time.time(), "kind": kind, **kw}
        with self._audit_lock:
            p = self.home / "audit.log"
            try:
                if p.exists() and p.stat().st_size > 5_000_000:
                    p.replace(self.home / "audit.log.1")
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            except Exception:
                pass


# --------------------------------------------------------------------------------------------------
# policy helpers
# --------------------------------------------------------------------------------------------------
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh", "nu", "elvish", "xonsh"}
INTERPRETERS = SHELLS | {"python", "python3", "py", "pythonw", "node", "deno", "bun", "perl", "ruby", "php", "lua", "tclsh", "osascript",
                         "wscript", "cscript", "env", "busybox", "npx", "uvx", "pipx"}
GIT_EXEC = re.compile(r"(?i)^(alias\.[^=]*=!|core\.(sshcommand|pager|editor|fsmonitor|hookspath)=|[^=]*\.(command|cmd|program)=)")
ALWAYS_RISKY = {"mshta", "rundll32", "regsvr32", "sudo", "doas", "pkexec", "runas", "gsudo", "su", "awk", "gawk", "mawk", "nawk", "sed",
                "at", "schtasks", "crontab", "systemd-run", "launchctl", "curl", "wget", "invoke-expression", "iex"}
# single-dash clusters with c/e (-c -lc -ec -pe -e), PowerShell's abbreviations of -Command/-EncodedCommand (-en, -enc, -comm …),
# --eval[=…] / --print[=…], cmd's /c /k /r with or without a space, env -S, and deno/bun 'eval' subcommands
INLINE_FLAG = re.compile(r"^(-[a-z]*[ce][a-z]*|-en[a-z]*|-comm[a-z]*|-encodedcommand|--eval(=.*)?|--print(=.*)?|-p|-r|-S|/[ckr].*|eval|-command)$", re.I)


def allowlist_problem(argv) -> Optional[str]:
    """why an allow-list argv could run arbitrary code (None = fine): shells or interpreters given inline code,
    wrappers that re-exec (env sh -c …), elevation, wildcards"""
    if not argv:
        return None
    argv = [str(a) for a in argv]
    names = [Path(a.replace("\\", "/")).name.lower().removesuffix(".exe") for a in argv]
    for i, n in enumerate(names):
        if n in ALWAYS_RISKY:
            return f"{n} in the allow-list"
        if n in INTERPRETERS and any(INLINE_FLAG.match(a) for a in argv[i + 1:]):
            return f"{n} with inline code ({' '.join(argv[i:i + 3])} …)"
        if n == "git":
            rest = argv[i + 1:]
            if any(a == "-c" and j + 1 < len(rest) and GIT_EXEC.match(rest[j + 1]) for j, a in enumerate(rest)) or any(a.startswith("--config-env") for a in rest):
                return "git configured to run a command (-c alias.x=!… / core.sshCommand …)"
    if any(ch in a for a in argv for ch in "*?"):
        return "wildcard in the allow-list"
    return None


SECRET_PREFIX = re.compile(r"^(sk-|sk_live_|rk_live_|ghp_|gho_|ghs_|github_pat_|glpat-|xox[abpr]-|AKIA|ASIA|AIza|ya29\.|eyJ[\w-]{8,}\.)")


def looks_secret(s: str) -> bool:
    """heuristic for clipboard entries that should not be projected in clear: API-key prefixes, or a short
    whitespace-free string mixing ≥ 3 character classes without word-like lowercase runs (generated passwords)"""
    t = s.strip()
    if not t or len(t) > 256 or any(c.isspace() for c in t):
        return False
    if SECRET_PREFIX.match(t):
        return True
    if not 8 <= len(t) <= 64 or "://" in t or t[0] in "/~.\\" or re.search(r"[a-z]{4,}", t):
        return False
    classes = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    return classes >= 3


def local_addresses() -> set:
    """names and addresses of this machine — the Host/Origin allow-list for LAN mode"""
    out = {"127.0.0.1", "localhost", "::1"}
    try:
        hn = socket.gethostname().lower()
        out |= {hn, hn + ".local", hn.split(".")[0], hn.split(".")[0] + ".local"}
        for info in socket.getaddrinfo(socket.gethostname(), None):
            out.add(str(info[4][0]).split("%")[0].lower())
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))                                   # no packet is sent; picks the outbound interface
        out.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    if psutil is not None:
        try:
            for addrs in psutil.net_if_addrs().values():
                for a in addrs:
                    if a.family in (socket.AF_INET, socket.AF_INET6):
                        out.add(str(a.address).split("%")[0].lower())
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------------------------------
# small math: One Euro filter, homographies, Gray code
# --------------------------------------------------------------------------------------------------
class OneEuro:
    """Casiez, Roussel, Vogel — CHI 2012."""

    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self.mc, self.beta, self.dc = min_cutoff, beta, d_cutoff
        self.x = None
        self.dx = 0.0
        self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(1e-4, t - self.t)
        dx = (x - self.x) / dt
        edx = self.dx + self._alpha(self.dc, dt) * (dx - self.dx)
        cut = self.mc + self.beta * abs(edx)
        ex = self.x + self._alpha(cut, dt) * (x - self.x)
        self.x, self.dx, self.t = ex, edx, t
        return ex


def homography_dlt(src, dst):
    """Normalised DLT (Hartley). src/dst: (N,2) sequences, N ≥ 4. Returns 3×3 list or None."""
    if np is None or len(src) < 4:
        return None
    s = np.asarray(src, float)
    d = np.asarray(dst, float)

    def norm(p):
        c = p.mean(0)
        md = np.mean(np.linalg.norm(p - c, axis=1)) or 1.0
        k = math.sqrt(2) / md
        return np.array([[k, 0, -k * c[0]], [0, k, -k * c[1]], [0, 0, 1]])

    Ts, Td = norm(s), norm(d)
    sh = (Ts @ np.c_[s, np.ones(len(s))].T).T
    dh = (Td @ np.c_[d, np.ones(len(d))].T).T
    A = []
    for (x, y, _), (u, v, _) in zip(sh, dh):
        A.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        A.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, Vt = np.linalg.svd(np.asarray(A))
    H = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ H @ Ts
    if abs(H[2, 2]) < 1e-12:
        return None
    return (H / H[2, 2]).tolist()


def h_apply(H, x, y):
    w = H[2][0] * x + H[2][1] * y + H[2][2]
    return ((H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w)


def homography_ransac(src, dst, thresh=3.0, iters=1000, seed=7):
    """Returns (H, inlier_idx, rms) or (None, [], nan)."""
    if np is None or len(src) < 4:
        return None, [], float("nan")
    if cv2 is not None:
        H, mask = cv2.findHomography(np.asarray(src, np.float64), np.asarray(dst, np.float64), cv2.RANSAC, thresh, maxIters=iters, confidence=0.995)
        if H is None:
            return None, [], float("nan")
        idx = [i for i, m in enumerate(mask.ravel()) if m]
        H = (H / H[2, 2]).tolist()
    else:
        rng = np.random.default_rng(seed)
        best, idx = None, []
        n = len(src)
        for _ in range(iters):
            pick = rng.choice(n, 4, replace=False)
            Hc = homography_dlt([src[i] for i in pick], [dst[i] for i in pick])
            if Hc is None:
                continue
            inl = [i for i in range(n) if math.dist(h_apply(Hc, *src[i]), dst[i]) < thresh]
            if len(inl) > len(idx):
                best, idx = Hc, inl
        H = homography_dlt([src[i] for i in idx], [dst[i] for i in idx]) if len(idx) >= 4 else best
        if H is None:
            return None, [], float("nan")
    errs = [math.dist(h_apply(H, *src[i]), dst[i]) ** 2 for i in idx]
    return H, idx, math.sqrt(sum(errs) / max(1, len(errs)))


def gray_plan(W, H, step):
    nx, ny = math.ceil(W / step), math.ceil(H / step)
    bx, by = max(1, math.ceil(math.log2(max(2, nx)))), max(1, math.ceil(math.log2(max(2, ny))))
    pats = [{"kind": "black"}, {"kind": "white"}]
    for b in range(bx):
        pats += [{"kind": "bit", "axis": "x", "b": b, "inv": False}, {"kind": "bit", "axis": "x", "b": b, "inv": True}]
    for b in range(by):
        pats += [{"kind": "bit", "axis": "y", "b": b, "inv": False}, {"kind": "bit", "axis": "y", "b": b, "inv": True}]
    return {"W": W, "H": H, "step": step, "nx": nx, "ny": ny, "bx": bx, "by": by, "pats": pats}


def gray_decode(plan, frames, thr_black=18.0, thr_white=3.0):
    """frames: list of float32 HxW images aligned with plan['pats'] → (col, row, valid) arrays."""
    B, Wt = frames[0], frames[1]
    valid = (Wt - B) > thr_black
    gx = np.zeros(B.shape, np.int32)
    gy = np.zeros(B.shape, np.int32)
    for b in range(plan["bx"]):
        v, vi = frames[2 + 2 * b], frames[3 + 2 * b]
        valid &= np.abs(v - vi) >= thr_white
        gx = (gx << 1) | (v > vi)
    off = 2 + 2 * plan["bx"]
    for b in range(plan["by"]):
        v, vi = frames[off + 2 * b], frames[off + 1 + 2 * b]
        valid &= np.abs(v - vi) >= thr_white
        gy = (gy << 1) | (v > vi)

    def dec(g):
        b = g.copy()
        s = g >> 1
        while s.any():
            b ^= s
            s >>= 1
        return b

    col, row = dec(gx), dec(gy)
    valid &= (col < plan["nx"]) & (row < plan["ny"])
    return col, row, valid


def gray_correspondences(plan, col, row, valid, min_px=2):
    """One (camera centroid ↔ cell centre in surface px) pair per decoded stripe cell."""
    ys, xs = np.nonzero(valid)
    if len(xs) == 0:
        return [], []
    key = row[ys, xs].astype(np.int64) * plan["nx"] + col[ys, xs]
    order = np.argsort(key)
    key, xs, ys = key[order], xs[order], ys[order]
    uniq, start, counts = np.unique(key, return_index=True, return_counts=True)
    sx = np.add.reduceat(xs + 0.5, start)
    sy = np.add.reduceat(ys + 0.5, start)
    cam, surf = [], []
    for k, c, x, y in zip(uniq, counts, sx, sy):
        if c < min_px:
            continue
        cam.append((x / c, y / c))
        surf.append((((k % plan["nx"]) + 0.5) * plan["step"], ((k // plan["nx"]) + 0.5) * plan["step"]))
    return cam, surf


# --------------------------------------------------------------------------------------------------
# OSC 1.0 (enough for TUIO): encode + decode, bundles
# --------------------------------------------------------------------------------------------------
def _osc_str(s: str) -> bytes:
    b = s.encode() + b"\0"
    return b + b"\0" * ((4 - len(b) % 4) % 4)


def osc_message(addr: str, *args) -> bytes:
    tags, data = ",", b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"
            data += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            data += struct.pack(">f", a)
        elif isinstance(a, (bytes, bytearray)):
            tags += "b"
            data += struct.pack(">i", len(a)) + bytes(a) + b"\0" * ((4 - len(a) % 4) % 4)
        else:
            tags += "s"
            data += _osc_str(str(a))
    return _osc_str(addr) + _osc_str(tags) + data


def osc_bundle(*msgs: bytes, timetag: int = 1) -> bytes:
    out = _osc_str("#bundle") + struct.pack(">Q", timetag)
    for m in msgs:
        out += struct.pack(">i", len(m)) + m
    return out


def osc_parse(data: bytes) -> list:
    """→ list of (address, [args]); bundles flattened."""
    def rstr(b, i):
        j = b.index(b"\0", i)
        s = b[i:j].decode(errors="replace")
        return s, (j + 4) & ~3

    if data.startswith(b"#bundle\0"):
        out, i = [], 16
        while i + 4 <= len(data):
            n = struct.unpack(">i", data[i:i + 4])[0]
            out += osc_parse(data[i + 4:i + 4 + n])
            i += 4 + n
        return out
    addr, i = rstr(data, 0)
    tags, i = rstr(data, i)
    args = []
    for t in tags[1:]:
        if t == "i":
            args.append(struct.unpack(">i", data[i:i + 4])[0]); i += 4
        elif t == "f":
            args.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
        elif t == "s":
            s, i = rstr(data, i); args.append(s)
        elif t == "b":
            n = struct.unpack(">i", data[i:i + 4])[0]; args.append(data[i + 4:i + 4 + n]); i += 4 + ((n + 3) & ~3)
        elif t == "T":
            args.append(True)
        elif t == "F":
            args.append(False)
        elif t == "h":
            args.append(struct.unpack(">q", data[i:i + 8])[0]); i += 8
        elif t == "d":
            args.append(struct.unpack(">d", data[i:i + 8])[0]); i += 8
    return [(addr, args)]


# --------------------------------------------------------------------------------------------------
# chords: "mod+shift+p", sequences ["mod+k","z"], per-OS maps {"win":..,"mac":..,"linux":..,"all":..}
# --------------------------------------------------------------------------------------------------
MODS = {"ctrl", "shift", "alt", "win", "cmd", "super", "meta", "mod", "option", "control"}
KEY_ALIASES = {"return": "enter", "escape": "esc", "del": "delete", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
               "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down", "spacebar": "space", "bksp": "backspace",
               "plus": "=", "minus": "-", "grave": "`", "backtick": "`", "prtsc": "print", "printscreen": "print", "apps": "menu", "equal": "="}


def resolve_chord(spec, os_name: str = OS):
    """spec → list of (frozenset(mods), key). Returns [] if not available on this OS."""
    if spec is None:
        return []
    if isinstance(spec, dict):
        spec = spec.get(os_name, spec.get("all"))
        if spec is None:
            return []
    seq = spec if isinstance(spec, list) else [spec]
    out = []
    for one in seq:
        one = str(one).strip().lower()
        if not one:
            continue
        if one == "+":
            parts = ["+"]
        elif one.endswith("++"):
            parts = [p for p in one[:-2].split("+") if p] + ["+"]
        else:
            parts = [p for p in one.split("+") if p]
        *mod_parts, key = parts
        mods = {norm_mod(p, os_name) for p in mod_parts}
        key = KEY_ALIASES.get(key, key)
        if key in MODS:                                  # a lone modifier, e.g. "super"
            key = norm_mod(key, os_name)
        out.append((frozenset(mods), key))
    return out


def norm_mod(p: str, os_name: str = OS) -> str:
    m = {"control": "ctrl", "option": "alt", "meta": "win", "super": "win"}.get(p, p)
    if m == "mod":
        m = "cmd" if os_name == "mac" else "ctrl"
    if m == "win" and os_name == "mac":
        m = "cmd"
    if m == "cmd" and os_name != "mac":
        m = "win"
    return m
