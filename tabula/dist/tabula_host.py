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


# ==================================================================================================
# input injection backends
# ==================================================================================================
MEDIA_KEYS = {"playpause", "next", "prev", "stop", "volup", "voldown", "mute"}
US_SHIFTED = {'~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0', '_': '-', '+': '=',
              '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/'}


class Aborted(Exception):
    """raised inside an injection when the host disarmed (PANIC, palm, idle) while it was running"""


class InputBackend:
    name = "base"
    caps: set = set()

    def __init__(self):
        self.held_keys: set = set()
        self.held_buttons: set = set()
        self.touches: dict = {}

    # primitives (override)
    def key(self, key: str, down: bool): raise NotImplementedError
    def text(self, s: str): raise NotImplementedError
    def move(self, x: int, y: int): raise NotImplementedError
    def move_rel(self, dx: int, dy: int): raise NotImplementedError
    def button(self, btn: str, down: bool): raise NotImplementedError
    def wheel(self, dy: int = 0, dx: int = 0): raise NotImplementedError
    def touch_frame(self, contacts: list): raise NotImplementedError("no OS touch injection on this backend")
    def cursor(self):
        return None
    def can_type(self, s: str) -> bool:
        """True when text() reproduces s exactly on the current keyboard layout (else the host pastes)"""
        return True

    # composites
    def chord(self, mods, key):
        order = [m for m in ("ctrl", "alt", "shift", "win", "cmd") if m in mods]
        for m in order:
            self.key(m, True); self.held_keys.add(m)
        try:
            self.key(key, True); self.key(key, False)
        finally:
            for m in reversed(order):
                self.key(m, False); self.held_keys.discard(m)

    def media(self, op):
        self.key(op, True); self.key(op, False)

    def click(self, btn="left", n=1):
        for _ in range(n):
            self.button(btn, True); self.button(btn, False)

    def release_all(self):
        for k in list(self.held_keys):
            try:
                self.key(k, False)
            except Exception:
                pass
        self.held_keys.clear()
        for b in list(self.held_buttons):
            try:
                self.button(b, False)
            except Exception:
                pass
        self.held_buttons.clear()
        if self.touches:
            try:
                self.touch_frame([{"id": k, "x": v[0], "y": v[1], "phase": "up"} for k, v in self.touches.items()])
            except Exception:
                pass
            self.touches.clear()


class DryRunBackend(InputBackend):
    """Logs every call; injects nothing. Used by --dry-run and tests."""
    name = "dry-run"
    caps = {"touch"}

    def __init__(self):
        super().__init__()
        self.events = collections.deque(maxlen=2000)
        self.pos = (0, 0)

    def _rec(self, *e):
        self.events.append((time.time(),) + e)
        log.debug("DRY %s", e)

    def key(self, key, down): self._rec("key", key, down)
    def text(self, s): self._rec("text", s)
    def move(self, x, y): self.pos = (x, y); self._rec("move", x, y)
    def move_rel(self, dx, dy): self.pos = (self.pos[0] + dx, self.pos[1] + dy); self._rec("rel", dx, dy)
    def button(self, btn, down):
        (self.held_buttons.add if down else self.held_buttons.discard)(btn); self._rec("button", btn, down)
    def wheel(self, dy=0, dx=0): self._rec("wheel", dy, dx)
    def touch_frame(self, contacts):
        for c in contacts:
            if c["phase"] == "up":
                self.touches.pop(c["id"], None)
            else:
                self.touches[c["id"]] = (c["x"], c["y"])
        self._rec("touch", [(c["id"], c["phase"]) for c in contacts])
    def cursor(self): return list(self.pos)


# -------------------------------- Windows: SendInput + InjectTouchInput --------------------------------
class WindowsBackend(InputBackend):
    name = "windows-sendinput"
    caps = {"touch", "unicode"}
    VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
          "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "print": 0x2C, "capslock": 0x14, "menu": 0x5D,
          "ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B, "cmd": 0x5B,
          "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
          "numpad_mul": 0x6A, "numpad_add": 0x6B, "numpad_sub": 0x6D, "numpad_dec": 0x6E, "numpad_div": 0x6F, "numpad_enter": 0x0D,
          "playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "mute": 0xAD, "voldown": 0xAE, "volup": 0xAF}
    EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x6F, 0x5B, 0x5C, 0x5D, 0xA3, 0xA5, 0xB0, 0xB1, 0xB2, 0xB3, 0xAD, 0xAE, 0xAF, 0x2C}

    def __init__(self, punctuation="physical"):
        super().__init__()
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        try:                                                        # physical pixels everywhere
            self.u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        class POINTER_INFO(ctypes.Structure):
            _fields_ = [("pointerType", ctypes.c_uint32), ("pointerId", ctypes.c_uint32), ("frameId", ctypes.c_uint32), ("pointerFlags", ctypes.c_uint32),
                        ("sourceDevice", wintypes.HANDLE), ("hwndTarget", wintypes.HWND), ("ptPixelLocation", wintypes.POINT), ("ptHimetricLocation", wintypes.POINT),
                        ("ptPixelLocationRaw", wintypes.POINT), ("ptHimetricLocationRaw", wintypes.POINT), ("dwTime", wintypes.DWORD), ("historyCount", ctypes.c_uint32),
                        ("InputData", ctypes.c_int32), ("dwKeyStates", wintypes.DWORD), ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int)]

        class POINTER_TOUCH_INFO(ctypes.Structure):
            _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32), ("touchMask", ctypes.c_uint32), ("rcContact", wintypes.RECT),
                        ("rcContactRaw", wintypes.RECT), ("orientation", ctypes.c_uint32), ("pressure", ctypes.c_uint32)]

        self.MOUSEINPUT, self.KEYBDINPUT, self.INPUT, self.PTI = MOUSEINPUT, KEYBDINPUT, INPUT, POINTER_TOUCH_INFO
        self.u32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.u32.VkKeyScanW.restype = ctypes.c_short
        self.u32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
        self.punct_char = punctuation == "char"
        self.touch_ok = False
        try:
            self.touch_ok = bool(self.u32.InitializeTouchInjection(10, 1))     # TOUCH_FEEDBACK_DEFAULT
        except Exception:
            self.touch_ok = False
        if not self.touch_ok:
            self.caps = {"unicode"}
        self._slots: dict = {}
        self._tlock = threading.Lock()
        self._last_inject = 0.0
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _send(self, *inputs):
        arr = (self.INPUT * len(inputs))(*inputs)
        n = self.u32.SendInput(len(inputs), arr, self.ct.sizeof(self.INPUT))
        if n != len(inputs):
            log.debug("SendInput blocked (UIPI? elevated target window) err=%s", self.ct.get_last_error())

    def _vk(self, key):
        if len(key) == 1 and key.isalnum():
            return ord(key.upper()), 0
        if key in self.VK and not (self.punct_char and len(key) == 1):
            return self.VK[key], 0
        m = re.fullmatch(r"f(\d{1,2})", key)
        if m and 1 <= int(m.group(1)) <= 24:
            return 0x6F + int(m.group(1)), 0
        m = re.fullmatch(r"numpad(\d)", key)
        if m:
            return 0x60 + int(m.group(1)), 0
        if len(key) == 1:                                          # current layout lookup
            r = self.u32.VkKeyScanW(key)
            if r != -1:
                return r & 0xFF, (r >> 8) & 0xFF
        raise KeyError(key)

    def key(self, key, down):
        vk, _ = self._vk(key)
        scan = self.u32.MapVirtualKeyW(vk, 0)
        flags = (0 if down else 2) | (1 if vk in self.EXTENDED or key == "numpad_enter" else 0)
        self._send(self.INPUT(1, self.INPUT._fields_[1][1](ki=self.KEYBDINPUT(vk, scan, flags, 0, 0))))

    def chord(self, mods, key):
        vk, shift_state = self._vk(key)
        extra = set(mods)
        if shift_state & 1:
            extra.add("shift")
        super().chord(frozenset(extra), key)

    def text(self, s):
        U = self.INPUT._fields_[1][1]
        for ch in s.replace("\r\n", "\n"):
            if ch == "\n":
                self.chord(frozenset(), "enter")
                continue
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):                       # surrogate pairs → two code units
                cu = int.from_bytes(data[i:i + 2], "little")
                self._send(self.INPUT(1, U(ki=self.KEYBDINPUT(0, cu, 4, 0, 0))), self.INPUT(1, U(ki=self.KEYBDINPUT(0, cu, 4 | 2, 0, 0))))

    def move(self, x, y):
        self.u32.SetCursorPos(int(x), int(y))

    def move_rel(self, dx, dy):
        U = self.INPUT._fields_[1][1]
        self._send(self.INPUT(0, U(mi=self.MOUSEINPUT(int(dx), int(dy), 0, 0x0001, 0, 0))))

    def button(self, btn, down):
        f = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}[btn][0 if down else 1]
        U = self.INPUT._fields_[1][1]
        self._send(self.INPUT(0, U(mi=self.MOUSEINPUT(0, 0, 0, f, 0, 0))))
        (self.held_buttons.add if down else self.held_buttons.discard)(btn)

    def wheel(self, dy=0, dx=0):
        U = self.INPUT._fields_[1][1]
        if dy:
            self._send(self.INPUT(0, U(mi=self.MOUSEINPUT(0, 0, self.ct.c_uint32(int(-dy * 120)).value, 0x0800, 0, 0))))
        if dx:
            self._send(self.INPUT(0, U(mi=self.MOUSEINPUT(0, 0, self.ct.c_uint32(int(dx * 120)).value, 0x1000, 0, 0))))

    def cursor(self):
        p = self.wt.POINT()
        self.u32.GetCursorPos(self.ct.byref(p))
        return [p.x, p.y]

    # ---- touch: every frame carries every active contact; UP repeats the last UPDATE position ----
    def _info(self, slot, x, y, flags):
        t = self.PTI()
        t.pointerInfo.pointerType = 2                               # PT_TOUCH
        t.pointerInfo.pointerId = slot
        t.pointerInfo.ptPixelLocation.x, t.pointerInfo.ptPixelLocation.y = int(x), int(y)
        t.pointerInfo.pointerFlags = flags
        t.touchFlags, t.touchMask = 0, 0x7                          # contact area | orientation | pressure
        t.rcContact.left, t.rcContact.right, t.rcContact.top, t.rcContact.bottom = int(x) - 3, int(x) + 3, int(y) - 3, int(y) + 3
        t.orientation, t.pressure = 90, 32000
        return t

    def touch_frame(self, contacts):
        if not self.touch_ok:
            raise NotImplementedError("InitializeTouchInjection failed")
        with self._tlock:
            frame = []
            seen = set()
            for c in contacts:
                cid = c["id"]
                seen.add(cid)
                if c["phase"] == "up":
                    if cid in self._slots:
                        slot, lx, ly = self._slots.pop(cid)
                        frame.append(self._info(slot, lx, ly, 0x40000))            # UP at last position
                        self.touches.pop(cid, None)
                    continue
                if cid not in self._slots:
                    free = sorted(set(range(10)) - {s for s, _, _ in self._slots.values()})
                    if not free:
                        continue
                    self._slots[cid] = (free[0], c["x"], c["y"])
                    frame.append(self._info(free[0], c["x"], c["y"], 0x10000 | 0x2 | 0x4))   # DOWN|INRANGE|INCONTACT
                else:
                    slot = self._slots[cid][0]
                    self._slots[cid] = (slot, c["x"], c["y"])
                    frame.append(self._info(slot, c["x"], c["y"], 0x20000 | 0x2 | 0x4))     # UPDATE|INRANGE|INCONTACT
                self.touches[cid] = (c["x"], c["y"])
            for cid, (slot, lx, ly) in list(self._slots.items()):                          # contacts not mentioned stay down
                if cid not in seen:
                    frame.append(self._info(slot, lx, ly, 0x20000 | 0x2 | 0x4))
            self._inject(frame)

    def _inject(self, frame):
        if not frame:
            return
        arr = (self.PTI * len(frame))(*frame)
        for _ in range(3):
            if self.u32.InjectTouchInput(len(frame), arr):
                self._last_inject = time.time()
                return
            err = self.ct.get_last_error()
            if err == 21:                                                                    # ERROR_NOT_READY → retry after ≥0.1 ms
                time.sleep(0.002)
                continue
            log.debug("InjectTouchInput failed err=%s — cancelling contacts", err)
            self._slots.clear(); self.touches.clear()
            return

    def _keepalive(self):                                                                   # press-and-hold needs repeated UPDATE frames
        while True:
            time.sleep(0.05)
            with self._tlock:
                if self._slots and time.time() - self._last_inject > 0.06:
                    self._inject([self._info(s, x, y, 0x20000 | 0x2 | 0x4) for s, x, y in self._slots.values()])


# -------------------------------- macOS: Quartz CGEvent --------------------------------
class MacBackend(InputBackend):
    name = "macos-quartz"
    caps = {"unicode"}
    KC = {"a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
          "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C,
          "0": 0x1D, "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "enter": 0x24, "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29,
          "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "tab": 0x30, "space": 0x31, "`": 0x32, "backspace": 0x33, "esc": 0x35,
          "cmd": 0x37, "shift": 0x38, "capslock": 0x39, "alt": 0x3A, "ctrl": 0x3B, "numpad_dec": 0x41, "numpad_mul": 0x43, "numpad_add": 0x45,
          "numpad_div": 0x4B, "numpad_enter": 0x4C, "numpad_sub": 0x4E, "numpad0": 0x52, "numpad1": 0x53, "numpad2": 0x54, "numpad3": 0x55, "numpad4": 0x56,
          "numpad5": 0x57, "numpad6": 0x58, "numpad7": 0x59, "numpad8": 0x5B, "numpad9": 0x5C, "f5": 0x60, "f6": 0x61, "f7": 0x62, "f3": 0x63, "f8": 0x64,
          "f9": 0x65, "f11": 0x67, "f13": 0x69, "f14": 0x6B, "f10": 0x6D, "f12": 0x6F, "f15": 0x71, "insert": 0x72, "home": 0x73, "pageup": 0x74,
          "delete": 0x75, "f4": 0x76, "end": 0x77, "f2": 0x78, "pagedown": 0x79, "f1": 0x7A, "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E}
    FLAG = {"cmd": 0x100000, "shift": 0x20000, "ctrl": 0x40000, "alt": 0x80000}
    NX = {"volup": 0, "voldown": 1, "mute": 7, "playpause": 16, "next": 17, "prev": 18}

    def __init__(self):
        super().__init__()
        import Quartz  # type: ignore
        self.Q = Quartz
        self.pos = (0, 0)

    def _post(self, ev):
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def key(self, key, down):
        if key in self.NX:
            return self._media(key, down)
        ev = self.Q.CGEventCreateKeyboardEvent(None, self.KC[key], down)
        self._post(ev)

    def chord(self, mods, key):
        if key in self.NX:
            return self.media(key)
        flags = 0
        for m in mods:
            flags |= self.FLAG.get(m, 0)
        for down in (True, False):
            ev = self.Q.CGEventCreateKeyboardEvent(None, self.KC[key], down)
            self.Q.CGEventSetFlags(ev, flags)
            self._post(ev)

    def _media(self, key, down):
        from AppKit import NSEvent  # type: ignore
        code = self.NX[key]
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), 0xA00 if down else 0xB00, 0, 0, 0, 8, (code << 16) | ((0xA if down else 0xB) << 8), -1)
        self._post(ev.CGEvent())

    def text(self, s):
        for i in range(0, len(s), 16):
            chunk = s[i:i + 16]
            for down in (True, False):
                ev = self.Q.CGEventCreateKeyboardEvent(None, 0, down)
                self.Q.CGEventKeyboardSetUnicodeString(ev, len(chunk), chunk)
                self._post(ev)

    def move(self, x, y):
        self.pos = (x, y)
        t = self.Q.kCGEventLeftMouseDragged if "left" in self.held_buttons else self.Q.kCGEventMouseMoved
        self._post(self.Q.CGEventCreateMouseEvent(None, t, (x, y), self.Q.kCGMouseButtonLeft))

    def move_rel(self, dx, dy):
        c = self.cursor() or [0, 0]
        self.move(c[0] + dx, c[1] + dy)

    def button(self, btn, down):
        Q = self.Q
        c = self.cursor() or list(self.pos)
        t, b = {"left": ((Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp), Q.kCGMouseButtonLeft), "right": ((Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp), Q.kCGMouseButtonRight),
                "middle": ((Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp), Q.kCGMouseButtonCenter)}[btn]
        self._post(Q.CGEventCreateMouseEvent(None, t[0 if down else 1], tuple(c), b))
        (self.held_buttons.add if down else self.held_buttons.discard)(btn)

    def wheel(self, dy=0, dx=0):
        self._post(self.Q.CGEventCreateScrollWheelEvent(None, self.Q.kCGScrollEventUnitLine, 2, int(-dy), int(dx)))

    def cursor(self):
        p = self.Q.CGEventGetLocation(self.Q.CGEventCreate(None))
        return [p.x, p.y]


# -------------------------------- Linux: uinput (X11 + Wayland) --------------------------------
class UinputBackend(InputBackend):
    name = "linux-uinput"
    caps = {"touch"}

    def __init__(self, screen_box, layout="auto"):
        super().__init__()
        from evdev import UInput, ecodes as e, AbsInfo  # type: ignore
        self.layout = detect_xkb_layout() if layout in (None, "", "auto") else str(layout).lower()
        log.info("uinput keyboard layout: %s%s", self.layout, "" if self.layout == "us" else " → text is pasted (key codes are layout-blind)")
        self.e = e
        self.box = screen_box                                   # (x0, y0, w, h) of the virtual desktop
        W, H = max(1, screen_box[2]), max(1, screen_box[3])
        keys = [v for k, v in e.ecodes.items() if k.startswith("KEY_") and isinstance(v, int) and v < 0x2ff]
        self.kbd = UInput({e.EV_KEY: sorted(set(keys + [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE])), e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL]}, name="TABULA keyboard+mouse")
        self.ptr = UInput({e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE], e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, W - 1, 0, 0, 0)), (e.ABS_Y, AbsInfo(0, 0, H - 1, 0, 0, 0))]}, name="TABULA absolute pointer")
        self.ts = UInput({e.EV_KEY: [e.BTN_TOUCH, e.BTN_TOOL_FINGER, e.BTN_TOOL_DOUBLETAP, e.BTN_TOOL_TRIPLETAP, e.BTN_TOOL_QUADTAP],
                          e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, W - 1, 0, 0, 0)), (e.ABS_Y, AbsInfo(0, 0, H - 1, 0, 0, 0)), (e.ABS_MT_SLOT, AbsInfo(0, 0, 9, 0, 0, 0)),
                                     (e.ABS_MT_TRACKING_ID, AbsInfo(0, 0, 65535, 0, 0, 0)), (e.ABS_MT_POSITION_X, AbsInfo(0, 0, W - 1, 0, 0, 0)), (e.ABS_MT_POSITION_Y, AbsInfo(0, 0, H - 1, 0, 0, 0))]},
                         name="TABULA touchscreen", input_props=[e.INPUT_PROP_DIRECT])
        self._slots: dict = {}
        self._tid = 1
        self.pos = (0, 0)

    def _code(self, key):
        e = self.e
        named = {"enter": "ENTER", "esc": "ESC", "tab": "TAB", "space": "SPACE", "backspace": "BACKSPACE", "delete": "DELETE", "insert": "INSERT", "home": "HOME",
                 "end": "END", "pageup": "PAGEUP", "pagedown": "PAGEDOWN", "left": "LEFT", "right": "RIGHT", "up": "UP", "down": "DOWN", "`": "GRAVE", "-": "MINUS",
                 "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON", "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH",
                 "numpad_add": "KPPLUS", "numpad_sub": "KPMINUS", "numpad_mul": "KPASTERISK", "numpad_div": "KPSLASH", "numpad_dec": "KPDOT", "numpad_enter": "KPENTER",
                 "print": "SYSRQ", "capslock": "CAPSLOCK", "menu": "COMPOSE", "playpause": "PLAYPAUSE", "next": "NEXTSONG", "prev": "PREVIOUSSONG", "stop": "STOPCD",
                 "volup": "VOLUMEUP", "voldown": "VOLUMEDOWN", "mute": "MUTE", "ctrl": "LEFTCTRL", "shift": "LEFTSHIFT", "alt": "LEFTALT", "win": "LEFTMETA", "cmd": "LEFTMETA"}
        if key in named:
            return getattr(e, "KEY_" + named[key])
        m = re.fullmatch(r"numpad(\d)", key)
        if m:
            return getattr(e, "KEY_KP" + m.group(1))
        return getattr(e, "KEY_" + key.upper())

    def key(self, key, down):
        self.kbd.write(self.e.EV_KEY, self._code(key), 1 if down else 0)
        self.kbd.syn()

    def can_type(self, s):
        # evdev sends key *positions*: only a US layout turns them back into the same ASCII characters
        return self.layout == "us" and all(ch in "\n\t" or 32 <= ord(ch) < 127 for ch in s)

    def text(self, s):
        if not self.can_type(s):                                # validate the whole string before the first key
            raise NotImplementedError("uinput cannot type this text on layout %r — use clipboard paste" % self.layout)
        for ch in s:
            if ch == "\n":
                self.chord(frozenset(), "enter"); continue
            if ch == "\t":
                self.chord(frozenset(), "tab"); continue
            base, shift = (US_SHIFTED[ch], True) if ch in US_SHIFTED else (ch.lower(), ch.isupper())
            if ch == " ":
                base = "space"
            try:
                self.chord(frozenset({"shift"}) if shift else frozenset(), base)
            except AttributeError:
                raise NotImplementedError("uinput cannot type %r — use clipboard paste" % ch)

    def move(self, x, y):
        self.pos = (x, y)
        e = self.e
        self.ptr.write(e.EV_ABS, e.ABS_X, int(x - self.box[0]))
        self.ptr.write(e.EV_ABS, e.ABS_Y, int(y - self.box[1]))
        self.ptr.syn()

    def move_rel(self, dx, dy):
        e = self.e
        self.kbd.write(e.EV_REL, e.REL_X, int(dx)); self.kbd.write(e.EV_REL, e.REL_Y, int(dy)); self.kbd.syn()

    def button(self, btn, down):
        e = self.e
        code = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}[btn]
        dev = self.ptr
        dev.write(e.EV_KEY, code, 1 if down else 0); dev.syn()
        (self.held_buttons.add if down else self.held_buttons.discard)(btn)

    def wheel(self, dy=0, dx=0):
        e = self.e
        if dy:
            self.kbd.write(e.EV_REL, e.REL_WHEEL, int(-dy))
        if dx:
            self.kbd.write(e.EV_REL, e.REL_HWHEEL, int(dx))
        self.kbd.syn()

    def touch_frame(self, contacts):
        e, ts = self.e, self.ts
        for c in contacts:
            cid = c["id"]
            if c["phase"] == "up":
                if cid in self._slots:
                    ts.write(e.EV_ABS, e.ABS_MT_SLOT, self._slots.pop(cid))
                    ts.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, -1)
                self.touches.pop(cid, None)
                continue
            x, y = float(c["x"]), float(c["y"])
            if not (math.isfinite(x) and math.isfinite(y)):
                continue                                           # never leave a slot half-written
            if cid not in self._slots:
                free = sorted(set(range(10)) - set(self._slots.values()))
                if not free:
                    continue
                self._slots[cid] = free[0]
                ts.write(e.EV_ABS, e.ABS_MT_SLOT, free[0])
                ts.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, self._tid)
                self._tid = self._tid % 65000 + 1
            else:
                ts.write(e.EV_ABS, e.ABS_MT_SLOT, self._slots[cid])
            x, y = int(c["x"] - self.box[0]), int(c["y"] - self.box[1])
            ts.write(e.EV_ABS, e.ABS_MT_POSITION_X, x); ts.write(e.EV_ABS, e.ABS_MT_POSITION_Y, y)
            self.touches[cid] = (c["x"], c["y"])
        n = len(self._slots)
        ts.write(e.EV_KEY, e.BTN_TOUCH, 1 if n else 0)
        for code, k in ((e.BTN_TOOL_FINGER, 1), (e.BTN_TOOL_DOUBLETAP, 2), (e.BTN_TOOL_TRIPLETAP, 3), (e.BTN_TOOL_QUADTAP, 4)):
            ts.write(e.EV_KEY, code, 1 if n == k else 0)
        if n:
            first = next(iter(self.touches.values()))
            ts.write(e.EV_ABS, e.ABS_X, int(first[0] - self.box[0])); ts.write(e.EV_ABS, e.ABS_Y, int(first[1] - self.box[1]))
        ts.syn()

    def cursor(self):
        return list(self.pos)


# -------------------------------- Linux X11 via xdotool (no special permissions) --------------------------------
class XdotoolBackend(InputBackend):
    name = "x11-xdotool"
    caps = {"unicode"}
    SYM = {"enter": "Return", "esc": "Escape", "tab": "Tab", "space": "space", "backspace": "BackSpace", "delete": "Delete", "insert": "Insert", "home": "Home", "end": "End",
           "pageup": "Prior", "pagedown": "Next", "left": "Left", "right": "Right", "up": "Up", "down": "Down", "`": "grave", "-": "minus", "=": "equal",
           "[": "bracketleft", "]": "bracketright", "\\": "backslash", ";": "semicolon", "'": "apostrophe", ",": "comma", ".": "period", "/": "slash",
           "numpad_add": "KP_Add", "numpad_sub": "KP_Subtract", "numpad_mul": "KP_Multiply", "numpad_div": "KP_Divide", "numpad_dec": "KP_Decimal", "numpad_enter": "KP_Enter",
           "print": "Print", "capslock": "Caps_Lock", "menu": "Menu", "playpause": "XF86AudioPlay", "next": "XF86AudioNext", "prev": "XF86AudioPrev", "stop": "XF86AudioStop",
           "volup": "XF86AudioRaiseVolume", "voldown": "XF86AudioLowerVolume", "mute": "XF86AudioMute", "ctrl": "ctrl", "shift": "shift", "alt": "alt", "win": "super", "cmd": "super"}

    def __init__(self):
        super().__init__()
        if not shutil.which("xdotool"):
            raise RuntimeError("xdotool not installed")

    def _x(self, *args):
        subprocess.run(["xdotool", *map(str, args)], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _sym(self, key):
        m = re.fullmatch(r"numpad(\d)", key)
        if m:
            return "KP_" + m.group(1)
        if re.fullmatch(r"f\d{1,2}", key):
            return key.upper()
        return self.SYM.get(key, key)

    def key(self, key, down): self._x("keydown" if down else "keyup", self._sym(key))
    def chord(self, mods, key): self._x("key", "--clearmodifiers", "+".join([self._sym(m) for m in mods] + [self._sym(key)]))
    def text(self, s): self._x("type", "--delay", "4", "--", s)
    def move(self, x, y): self._x("mousemove", int(x), int(y))
    def move_rel(self, dx, dy): self._x("mousemove_relative", "--", int(dx), int(dy))
    def button(self, btn, down):
        self._x("mousedown" if down else "mouseup", {"left": 1, "middle": 2, "right": 3}[btn])
        (self.held_buttons.add if down else self.held_buttons.discard)(btn)
    def wheel(self, dy=0, dx=0):
        for _ in range(abs(int(dy))):
            self._x("click", 4 if dy < 0 else 5)
        for _ in range(abs(int(dx))):
            self._x("click", 7 if dx > 0 else 6)
    def cursor(self):
        try:
            out = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True, timeout=2).stdout
            d = dict(l.split("=", 1) for l in out.split() if "=" in l)
            return [int(d["X"]), int(d["Y"])]
        except Exception:
            return None


# -------------------------------- anywhere: pynput --------------------------------
class PynputBackend(InputBackend):
    name = "pynput"
    caps = {"unicode"}

    def __init__(self):
        super().__init__()
        from pynput import keyboard, mouse  # type: ignore
        self.kb, self.ms, self.K, self.B = keyboard.Controller(), mouse.Controller(), keyboard.Key, mouse.Button

    def _k(self, key):
        K = self.K
        m = {"enter": K.enter, "esc": K.esc, "tab": K.tab, "space": K.space, "backspace": K.backspace, "delete": K.delete, "home": K.home, "end": K.end,
             "pageup": K.page_up, "pagedown": K.page_down, "left": K.left, "right": K.right, "up": K.up, "down": K.down, "ctrl": K.ctrl, "shift": K.shift,
             "alt": K.alt, "win": K.cmd, "cmd": K.cmd, "capslock": K.caps_lock, "playpause": K.media_play_pause, "next": K.media_next, "prev": K.media_previous,
             "volup": K.media_volume_up, "voldown": K.media_volume_down, "mute": K.media_volume_mute}
        if key in m:
            return m[key]
        if re.fullmatch(r"f\d{1,2}", key):
            return getattr(K, key)
        if key == "insert" and hasattr(K, "insert"):
            return K.insert
        if key == "print" and hasattr(K, "print_screen"):
            return K.print_screen
        if key.startswith("numpad"):
            return {"numpad_add": "+", "numpad_sub": "-", "numpad_mul": "*", "numpad_div": "/", "numpad_dec": ".", "numpad_enter": K.enter}.get(key, key[-1])
        return key

    def key(self, key, down): (self.kb.press if down else self.kb.release)(self._k(key))
    def text(self, s): self.kb.type(s)
    def move(self, x, y): self.ms.position = (int(x), int(y))
    def move_rel(self, dx, dy): self.ms.move(int(dx), int(dy))
    def button(self, btn, down):
        (self.ms.press if down else self.ms.release)({"left": self.B.left, "right": self.B.right, "middle": self.B.middle}[btn])
        (self.held_buttons.add if down else self.held_buttons.discard)(btn)
    def wheel(self, dy=0, dx=0): self.ms.scroll(int(dx), int(-dy))
    def cursor(self): return list(self.ms.position)


def detect_xkb_layout() -> str:
    """first configured XKB layout (GNOME/KDE settings, $XKB_DEFAULT_LAYOUT, setxkbmap, localectl) or 'unknown'"""
    def run(argv):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=2).stdout
        except Exception:
            return ""
    def first(layouts, variants=""):
        lay = layouts.split(",")[0].strip().lower()
        var = (variants or "").split(",")[0].strip().lower()
        return lay + ("+" + var if var else "")               # 'us+dvorak', 'us+intl' ≠ 'us'
    v = os.environ.get("XKB_DEFAULT_LAYOUT")
    if v:
        return first(v, os.environ.get("XKB_DEFAULT_VARIANT", ""))
    if shutil.which("gsettings"):
        m = re.search(r"\('xkb',\s*'([^']+)'", run(["gsettings", "get", "org.gnome.desktop.input-sources", "sources"]))
        if m:
            return m.group(1).lower()
    for kr in ("kreadconfig6", "kreadconfig5"):
        if shutil.which(kr):
            out = run([kr, "--file", "kxkbrc", "--group", "Layout", "--key", "LayoutList"]).strip()
            if out:
                return first(out, run([kr, "--file", "kxkbrc", "--group", "Layout", "--key", "VariantList"]).strip())
    if shutil.which("setxkbmap"):
        q = run(["setxkbmap", "-query"])
        m = re.search(r"^layout:\s*(\S+)", q, re.M)
        if m:
            mv = re.search(r"^variant:\s*(\S+)", q, re.M)
            return first(m.group(1), mv.group(1) if mv else "")
    if shutil.which("localectl"):
        q = run(["localectl", "status"])
        m = re.search(r"X11 Layout:\s*(\S+)", q)
        if m:
            mv = re.search(r"X11 Variant:\s*(\S+)", q)
            return first(m.group(1), mv.group(1) if mv else "")
    return "unknown"


class Guarded:
    """Wraps the backend: every injection is serialised under one lock (typing threads, pointer, touch, watchdogs
    never interleave inside a key chord or an evdev frame) and refused the instant the host is no longer armed,
    so a PANIC stops a long string mid-way. Releases always go through."""
    INJECT = {"key", "text", "move", "move_rel", "button", "wheel", "touch_frame", "chord", "media", "click"}

    def __init__(self, inner: InputBackend, allowed: Callable[[], bool]):
        self._inner, self._allowed, self._lock = inner, allowed, threading.RLock()

    @staticmethod
    def _is_release(name, args, kw):
        if name in ("key", "button"):
            return (args[1] if len(args) > 1 else kw.get("down", True)) is False
        if name == "touch_frame":
            cs = args[0] if args else kw.get("contacts", [])
            return bool(cs) and all(c.get("phase") == "up" for c in cs)
        return False

    def __getattr__(self, name):
        v = getattr(self._inner, name)
        if not callable(v) or name not in self.INJECT and name != "release_all":
            return v

        def call(*args, **kw):
            with self._lock:
                if name in self.INJECT and not self._is_release(name, args, kw) and not self._allowed():
                    raise Aborted(name + " refused: not armed")
                out = v(*args, **kw)
                if name == "key" and args:
                    (self._inner.held_keys.add if (args[1] if len(args) > 1 else kw.get("down", True)) else self._inner.held_keys.discard)(args[0])
                return out
        return call


def make_backend(choice: str, dry: bool, screen_box, punctuation="physical", layout="auto") -> InputBackend:
    if dry or choice in ("dry", "dry-run"):
        return DryRunBackend()
    order = {"auto": {"win": ["windows", "pynput"], "mac": ["mac", "pynput"], "linux": ["uinput", "x11", "pynput"]}[OS]}.get(choice, [choice])
    errs = []
    for c in order:
        try:
            if c == "windows":
                return WindowsBackend(punctuation)
            if c == "mac":
                return MacBackend()
            if c == "uinput":
                return UinputBackend(screen_box, layout)
            if c == "x11":
                if not os.environ.get("DISPLAY"):
                    raise RuntimeError("no $DISPLAY")
                return XdotoolBackend()
            if c == "pynput":
                return PynputBackend()
        except Exception as ex:
            errs.append(f"{c}: {ex}")
    log.warning("no input backend could start (%s) — falling back to DRY-RUN", "; ".join(errs))
    return DryRunBackend()


# ==================================================================================================
# platform services: screens, focused window, window control, clipboard, capture
# ==================================================================================================
def _run(argv, timeout=2.0) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


class Platform:
    """Best available implementation per OS; every method degrades to None/[] instead of raising."""

    def __init__(self):
        self.wayland = OS == "linux" and bool(os.environ.get("WAYLAND_DISPLAY"))
        self.x11 = OS == "linux" and bool(os.environ.get("DISPLAY")) and not self.wayland
        self._mss = None
        self.focus_via = "none"
        if OS == "win":
            import ctypes
            from ctypes import wintypes
            self.ct, self.wt = ctypes, wintypes
            self.u32 = ctypes.WinDLL("user32", use_last_error=True)
            try:
                self.dwm = ctypes.WinDLL("dwmapi")
            except Exception:
                self.dwm = None
            self.focus_via = "win32"
        elif OS == "mac":
            try:
                import Quartz  # type: ignore
                from AppKit import NSWorkspace  # type: ignore
                self.Q, self.NSWorkspace = Quartz, NSWorkspace
                self.focus_via = "NSWorkspace"
            except Exception:
                self.Q = None
        else:
            if shutil.which("hyprctl") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
                self.focus_via = "hyprctl"
            elif shutil.which("swaymsg") and os.environ.get("SWAYSOCK"):
                self.focus_via = "sway"
            elif shutil.which("kdotool") and self.wayland:
                self.focus_via = "kdotool"
            elif self.x11 and shutil.which("xprop"):
                self.focus_via = "xprop"
            elif self.wayland and shutil.which("gdbus"):
                self.focus_via = "gnome-window-calls"

    # ---------------- screens ----------------
    def screens(self) -> list:
        """monitors in desktop coordinates, cached for 2 s (pointer moves clamp against them hundreds of times a second)"""
        now = time.monotonic()
        cached = getattr(self, "_scr", None)
        if cached and now - cached[0] < 2.0:
            return [dict(x) for x in cached[1]]
        out = self._screens()
        self._scr = (now, out)
        return [dict(x) for x in out]

    def _screens(self) -> list:
        out = []
        if mss_mod is not None:
            try:
                with mss_mod.mss() as m:
                    for i, mon in enumerate(m.monitors[1:]):
                        out.append({"id": i, "name": f"DISPLAY {i + 1}", "x": mon["left"], "y": mon["top"], "w": mon["width"], "h": mon["height"], "primary": mon["left"] == 0 and mon["top"] == 0})
            except Exception as e:
                log.debug("mss monitors: %s", e)
        if not out and OS == "linux":
            for line in _run(["xrandr", "--listmonitors"]).splitlines()[1:]:
                m = re.search(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)", line)
                if m:
                    w, h, x, y, name = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
                    out.append({"id": len(out), "name": name, "x": x, "y": y, "w": w, "h": h, "primary": "*" in line})
        if not out:
            out = [{"id": 0, "name": "VIRTUAL", "x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True, "virtual": True}]
        if not any(s["primary"] for s in out):
            out[0]["primary"] = True
        return out

    def desktop_box(self):
        s = self.screens()
        x0, y0 = min(a["x"] for a in s), min(a["y"] for a in s)
        return (x0, y0, max(a["x"] + a["w"] for a in s) - x0, max(a["y"] + a["h"] for a in s) - y0)

    # ---------------- focused window ----------------
    def focus(self) -> Optional[dict]:
        try:
            return getattr(self, "_focus_" + self.focus_via.replace("-", "_"))()
        except Exception as e:
            log.debug("focus(%s): %s", self.focus_via, e)
            return None

    def _focus_none(self):
        return None

    def _pname(self, pid):
        if psutil and pid:
            try:
                return psutil.Process(pid).name()
            except Exception:
                return ""
        return ""

    def _focus_win32(self):
        h = self.u32.GetForegroundWindow()
        if not h:
            return None
        n = self.u32.GetWindowTextLengthW(h)
        buf = self.ct.create_unicode_buffer(n + 1)
        self.u32.GetWindowTextW(h, buf, n + 1)
        pid = self.wt.DWORD()
        self.u32.GetWindowThreadProcessId(h, self.ct.byref(pid))
        exe = self._pname(pid.value)
        return {"app": exe.rsplit(".", 1)[0] if exe else "?", "exe": exe.lower(), "title": buf.value, "pid": pid.value, "id": int(h), "rect": self._rect_win(h)}

    def _rect_win(self, h):
        r = self.wt.RECT()
        if self.dwm is not None and self.dwm.DwmGetWindowAttribute(h, 9, self.ct.byref(r), self.ct.sizeof(r)) == 0:   # DWMWA_EXTENDED_FRAME_BOUNDS
            pass
        else:
            self.u32.GetWindowRect(h, self.ct.byref(r))
        return [r.left, r.top, r.right - r.left, r.bottom - r.top]

    def _focus_NSWorkspace(self):
        app = self.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        title, rect = "", None
        Q = self.Q
        for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements, Q.kCGNullWindowID) or []:
            if int(w.get("kCGWindowOwnerPID", -1)) == pid and int(w.get("kCGWindowLayer", 1)) == 0:
                title = str(w.get("kCGWindowName") or "")
                b = w.get("kCGWindowBounds") or {}
                rect = [int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))]
                break
        name = str(app.localizedName() or "")
        return {"app": name, "exe": name.lower(), "bundle": str(app.bundleIdentifier() or ""), "title": title, "pid": pid, "rect": rect}

    def _focus_xprop(self):
        m = re.search(r"window id # (0x[0-9a-f]+)", _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
        if not m or m.group(1) == "0x0":
            return None
        wid = m.group(1)
        out = _run(["xprop", "-id", wid, "WM_CLASS", "_NET_WM_NAME", "_NET_WM_PID"])
        cls = re.findall(r'WM_CLASS\(STRING\) = "([^"]*)", "([^"]*)"', out)
        name = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', out)
        pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", out)
        exe = self._pname(int(pid.group(1))) if pid else (cls[0][0] if cls else "")
        geo = _run(["xwininfo", "-id", wid])
        g = {k: int(v) for k, v in re.findall(r"(Absolute upper-left X|Absolute upper-left Y|Width|Height):\s+(-?\d+)", geo)}
        rect = [g.get("Absolute upper-left X", 0), g.get("Absolute upper-left Y", 0), g.get("Width", 0), g.get("Height", 0)] if g else None
        return {"app": cls[0][1] if cls else exe, "exe": exe.lower(), "title": name.group(1) if name else "", "pid": int(pid.group(1)) if pid else 0, "id": int(wid, 16), "rect": rect}

    def _focus_hyprctl(self):
        d = json.loads(_run(["hyprctl", "activewindow", "-j"]) or "{}")
        if not d:
            return None
        return {"app": d.get("class", ""), "exe": self._pname(d.get("pid")).lower() or d.get("class", "").lower(), "title": d.get("title", ""), "pid": d.get("pid", 0),
                "id": d.get("address"), "rect": d.get("at", [0, 0]) + d.get("size", [0, 0])}

    def _focus_sway(self):
        tree = json.loads(_run(["swaymsg", "-t", "get_tree"]) or "{}")
        stack = [tree]
        while stack:
            n = stack.pop()
            if n.get("focused") and n.get("type") in ("con", "floating_con"):
                r = n.get("rect", {})
                app = n.get("app_id") or (n.get("window_properties") or {}).get("class", "")
                return {"app": app, "exe": self._pname(n.get("pid")).lower() or str(app).lower(), "title": n.get("name", ""), "pid": n.get("pid", 0), "id": n.get("id"),
                        "rect": [r.get("x", 0), r.get("y", 0), r.get("width", 0), r.get("height", 0)]}
            stack += n.get("nodes", []) + n.get("floating_nodes", [])
        return None

    def _focus_kdotool(self):
        wid = _run(["kdotool", "getactivewindow"]).strip()
        if not wid:
            return None
        title = _run(["kdotool", "getwindowname", wid]).strip()
        cls = _run(["kdotool", "getwindowclassname", wid]).strip()
        pid = _run(["kdotool", "getwindowpid", wid]).strip()
        return {"app": cls, "exe": self._pname(int(pid)).lower() if pid.isdigit() else cls.lower(), "title": title, "pid": int(pid) if pid.isdigit() else 0, "id": wid, "rect": None}

    def _focus_gnome_window_calls(self):
        # needs the "Window Calls" GNOME Shell extension (GNOME offers no public focus API on Wayland)
        out = _run(["gdbus", "call", "--session", "--dest", "org.gnome.Shell", "--object-path", "/org/gnome/Shell/Extensions/Windows", "--method", "org.gnome.Shell.Extensions.Windows.List"])
        m = re.search(r"\('(.*)',\)", out, re.S)
        if not m:
            return None
        for w in json.loads(m.group(1).encode().decode("unicode_escape")):
            if w.get("focus"):
                return {"app": w.get("wm_class", ""), "exe": self._pname(w.get("pid")).lower() or w.get("wm_class", "").lower(), "title": w.get("title", ""), "pid": w.get("pid", 0), "id": w.get("id"), "rect": None}
        return None

    # ---------------- window list + control ----------------
    def windows(self) -> list:
        try:
            if OS == "win":
                return self._win_list_win32()
            if OS == "mac" and self.Q is not None:
                return self._win_list_mac()
            if self.x11 and shutil.which("wmctrl"):
                return self._win_list_wmctrl()
        except Exception as e:
            log.debug("windows(): %s", e)
        return []

    def _win_list_win32(self):
        out = []
        EnumProc = self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)
        cloaked = self.wt.DWORD()

        def cb(h, _):
            if not self.u32.IsWindowVisible(h) or self.u32.GetWindowTextLengthW(h) == 0:
                return True
            if self.u32.GetWindowLongW(h, -20) & 0x80:                        # WS_EX_TOOLWINDOW
                return True
            if self.dwm is not None and self.dwm.DwmGetWindowAttribute(h, 14, self.ct.byref(cloaked), 4) == 0 and cloaked.value:
                return True
            n = self.u32.GetWindowTextLengthW(h)
            buf = self.ct.create_unicode_buffer(n + 1)
            self.u32.GetWindowTextW(h, buf, n + 1)
            pid = self.wt.DWORD()
            self.u32.GetWindowThreadProcessId(h, self.ct.byref(pid))
            out.append({"id": int(h), "title": buf.value, "app": self._pname(pid.value).lower(), "rect": self._rect_win(h), "min": bool(self.u32.IsIconic(h))})
            return True

        self.u32.EnumWindows(EnumProc(cb), 0)
        return out[:40]

    def _win_list_mac(self):
        Q, out = self.Q, []
        for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements, Q.kCGNullWindowID) or []:
            if int(w.get("kCGWindowLayer", 1)) != 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            out.append({"id": int(w.get("kCGWindowNumber", 0)), "pid": int(w.get("kCGWindowOwnerPID", 0)), "title": str(w.get("kCGWindowName") or w.get("kCGWindowOwnerName") or ""),
                        "app": str(w.get("kCGWindowOwnerName") or "").lower(), "rect": [int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))], "min": False})
        return out[:40]

    def _win_list_wmctrl(self):
        out = []
        for line in _run(["wmctrl", "-lpG"]).splitlines():
            p = line.split(None, 8)
            if len(p) < 9 or p[1] == "-1":
                continue
            wid, pid, x, y, w, h, title = int(p[0], 16), int(p[2]), int(p[3]), int(p[4]), int(p[5]), int(p[6]), p[8]
            out.append({"id": wid, "title": title, "app": self._pname(pid).lower(), "rect": [x, y, w, h], "min": False})
        return out[:40]

    def win_op(self, op: str, wid, rect=None) -> bool:
        try:
            if OS == "win":
                h = int(wid)
                if op == "focus":
                    if self.u32.IsIconic(h):
                        self.u32.ShowWindow(h, 9)
                    self.u32.keybd_event(0x12, 0, 0, 0); self.u32.keybd_event(0x12, 0, 2, 0)   # ALT tap lifts the foreground lock
                    return bool(self.u32.SetForegroundWindow(h))
                if op in ("min", "max", "restore"):
                    return bool(self.u32.ShowWindow(h, {"min": 6, "max": 3, "restore": 9}[op]) or True)
                if op == "close":
                    return bool(self.u32.PostMessageW(h, 0x0010, 0, 0))
                if op == "move" and rect:
                    self.u32.ShowWindow(h, 9)
                    # rect is in visible-frame (DWM) coordinates, as _rect_win reports; SetWindowPos wants the outer rect,
                    # which includes the invisible resize borders — add them back or every move shrinks the window
                    outer, vis = self.wt.RECT(), self.wt.RECT()
                    self.u32.GetWindowRect(h, self.ct.byref(outer))
                    dl = dt = dr = db = 0
                    if self.dwm is not None and self.dwm.DwmGetWindowAttribute(h, 9, self.ct.byref(vis), self.ct.sizeof(vis)) == 0:
                        dl, dt, dr, db = vis.left - outer.left, vis.top - outer.top, outer.right - vis.right, outer.bottom - vis.bottom
                    x, y, w, hh = (int(v) for v in rect[:4])
                    return bool(self.u32.SetWindowPos(h, 0, x - dl, y - dt, w + dl + dr, hh + dt + db, 0x0004 | 0x0010))   # NOZORDER | NOACTIVATE
            elif OS == "mac":
                if op == "focus":
                    from AppKit import NSRunningApplication  # type: ignore
                    pid = next((w["pid"] for w in self._win_list_mac() if w["id"] == int(wid)), None)
                    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid) if pid else None
                    return bool(app and app.activateWithOptions_(1 << 1))
                return False
            elif self.x11 and shutil.which("wmctrl"):
                w = hex(int(wid))
                if op == "focus":
                    return subprocess.run(["wmctrl", "-ia", w]).returncode == 0
                if op == "min" and shutil.which("xdotool"):
                    return subprocess.run(["xdotool", "windowminimize", str(int(wid))]).returncode == 0
                if op == "max":
                    return subprocess.run(["wmctrl", "-ir", w, "-b", "add,maximized_vert,maximized_horz"]).returncode == 0
                if op == "restore":
                    subprocess.run(["wmctrl", "-ir", w, "-b", "remove,maximized_vert,maximized_horz"])
                    return subprocess.run(["wmctrl", "-ia", w]).returncode == 0
                if op == "close":
                    return subprocess.run(["wmctrl", "-ic", w]).returncode == 0
                if op == "move" and rect:
                    return subprocess.run(["wmctrl", "-ir", w, "-e", "0,%d,%d,%d,%d" % tuple(int(v) for v in rect)]).returncode == 0
        except Exception as e:
            log.debug("win_op %s: %s", op, e)
        return False

    def window_rect(self, wid):
        if OS == "win":
            return self._rect_win(int(wid))
        for w in self.windows():
            if str(w["id"]) == str(wid):
                return w["rect"]
        return None

    # ---------------- clipboard ----------------
    def clip_concealed(self) -> bool:
        """True when the current clipboard content is flagged by a password manager as not-for-history:
        Windows ExcludeClipboardContentFromMonitorProcessing / 'Clipboard Viewer Ignore' / CanIncludeInClipboardHistory=0,
        macOS org.nspasteboard.ConcealedType / TransientType, KDE/KeePassXC x-kde-passwordManagerHint"""
        try:
            if OS == "win":
                reg = self.u32.RegisterClipboardFormatW
                reg.argtypes, reg.restype = (self.wt.LPCWSTR,), self.wt.UINT
                for name in ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore"):
                    f = reg(name)
                    if f and self.u32.IsClipboardFormatAvailable(f):
                        return True
                f = reg("CanIncludeInClipboardHistory")
                if f and self.u32.IsClipboardFormatAvailable(f) and self.u32.OpenClipboard(0):
                    try:
                        self.u32.GetClipboardData.restype = self.ct.c_void_p
                        h = self.u32.GetClipboardData(f)
                        k32 = self.ct.WinDLL("kernel32")
                        k32.GlobalLock.restype, k32.GlobalLock.argtypes = self.ct.c_void_p, (self.ct.c_void_p,)
                        k32.GlobalUnlock.argtypes = (self.ct.c_void_p,)
                        ptr = k32.GlobalLock(h) if h else None
                        if ptr:
                            v = self.ct.c_uint32.from_address(ptr).value
                            k32.GlobalUnlock(h)
                            return v == 0
                    finally:
                        self.u32.CloseClipboard()
                return False
            if OS == "mac":
                from AppKit import NSPasteboard  # type: ignore
                types = set(str(t) for t in (NSPasteboard.generalPasteboard().types() or []))
                return bool(types & {"org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType"})
            for argv in (["wl-paste", "--list-types"], ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"]):
                if shutil.which(argv[0]):
                    out = _run(argv, 1.0)
                    if out:
                        return "x-kde-passwordManagerHint" in out
        except Exception as e:
            log.debug("clip_concealed: %s", e)
        return False

    def clip_get(self) -> Optional[str]:
        if pyperclip is not None:
            try:
                return pyperclip.paste()
            except Exception:
                pass
        if OS == "win":
            try:
                k32 = self.ct.WinDLL("kernel32")
                k32.GlobalLock.restype = self.ct.c_void_p
                k32.GlobalLock.argtypes = (self.ct.c_void_p,)
                k32.GlobalUnlock.argtypes = (self.ct.c_void_p,)
                self.u32.GetClipboardData.restype = self.ct.c_void_p
                if not self.u32.OpenClipboard(0):
                    return None
                try:
                    h = self.u32.GetClipboardData(13)                                   # CF_UNICODETEXT
                    if not h:
                        return None
                    p = k32.GlobalLock(h)
                    s = self.ct.wstring_at(p)
                    k32.GlobalUnlock(h)
                    return s
                finally:
                    self.u32.CloseClipboard()
            except Exception:
                return None
        if OS == "mac":
            return _run(["pbpaste"]) or None
        for argv in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
            if shutil.which(argv[0]):
                out = _run(argv)
                if out:
                    return out
        return None

    def clip_set(self, text: str) -> bool:
        if pyperclip is not None:
            try:
                pyperclip.copy(text)
                return True
            except Exception:
                pass
        argvs = {"win": [["clip.exe"]], "mac": [["pbcopy"]]}.get(OS, [["wl-copy"], ["xclip", "-selection", "clipboard", "-i"], ["xsel", "-b", "-i"]])
        for argv in argvs:
            if shutil.which(argv[0]):
                try:
                    subprocess.run(argv, input=text.encode("utf-16-le" if argv[0] == "clip.exe" else "utf-8"), timeout=3, check=True)
                    return True
                except Exception:
                    continue
        return False

    # ---------------- pixels ----------------
    def grab(self, rect):
        """rect [x,y,w,h] in desktop coords → numpy BGR image or None."""
        if mss_mod is None or np is None:
            return None
        try:
            if self._mss is None:
                self._mss = mss_mod.mss()
            shot = self._mss.grab({"left": int(rect[0]), "top": int(rect[1]), "width": max(1, int(rect[2])), "height": max(1, int(rect[3]))})
            return np.asarray(shot)[:, :, :3]
        except Exception as e:
            log.debug("grab: %s", e)
            self._mss = None
            return None


def synthetic_screen(w=1280, h=720, t=0.0, title="TABULA-Ω synthetic screen", cursor=None):
    """A test card used when no display can be captured (headless, CI, --dry-run)."""
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (28, 22, 16)
    for x in range(0, w, 64):
        img[:, x] = (60, 52, 40)
    for y in range(0, h, 64):
        img[y, :] = (60, 52, 40)
    cx, cy = int(w / 2 + math.cos(t) * w * 0.3), int(h / 2 + math.sin(t * 1.3) * h * 0.3)
    if cv2 is not None:
        cv2.circle(img, (cx, cy), 36, (255, 240, 124), 3)
        cv2.putText(img, title, (32, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (230, 230, 230), 2, cv2.LINE_AA)
        cv2.putText(img, time.strftime("%H:%M:%S"), (32, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (97, 200, 255), 2, cv2.LINE_AA)
        if cursor:
            cv2.circle(img, (int(cursor[0]), int(cursor[1])), 8, (0, 180, 255), -1)
    else:
        img[max(0, cy - 20):cy + 20, max(0, cx - 20):cx + 20] = (255, 240, 124)
    return img


def encode_jpeg(img, quality=70) -> Optional[bytes]:
    if cv2 is not None:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        return buf.tobytes() if ok else None
    if Image is not None:
        b = io.BytesIO()
        Image.fromarray(img[:, :, ::-1]).save(b, "JPEG", quality=int(quality))
        return b.getvalue()
    return None


def resize_max(img, max_w):
    h, w = img.shape[:2]
    if w <= max_w:
        return img
    nh = int(h * max_w / w)
    if cv2 is not None:
        return cv2.resize(img, (int(max_w), nh), interpolation=cv2.INTER_AREA)
    step = max(1, int(round(w / max_w)))
    return img[::step, ::step]


# ==================================================================================================
# integrations: VLM/OCR, OBS WebSocket v5, MIDI, OSC/TUIO, telemetry
# ==================================================================================================
VLM_PROMPTS = {
    "ocr": "Transcribe all text in this image exactly, preserving line breaks. Return only the text.",
    "explain": "Explain what this shows in two or three plain sentences.",
    "translate": "Translate the text in this image. Return only the translation.",
    "summarize": "Summarise the text in this image in three bullet points.",
}


class VLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def describe(self) -> dict:
        c = self.cfg
        first = c["chain"][0] if c["chain"] else "none"
        cloud = first == "anthropic" or (c.get("allow_cloud") and "anthropic" in c["chain"] and bool(os.environ.get("ANTHROPIC_API_KEY")))
        model = {"ollama": c["model"], "openai": c.get("openai_model") or "?", "anthropic": c["anthropic_model"], "tesseract": "tesseract"}.get(first, "?")
        return {"provider": first, "model": model, "cloud": bool(cloud)}

    def _post(self, url, body, headers=None, timeout=120):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def ask(self, img_b64: str, mode: str, prompt: str = "") -> tuple:
        text = (VLM_PROMPTS.get(mode, VLM_PROMPTS["explain"]) + (" " + prompt if prompt else "")).strip()
        errs = []
        for prov in self.cfg["chain"]:
            try:
                if prov == "ollama":
                    r = self._post(self.cfg["ollama_url"].rstrip("/") + "/api/chat", {"model": self.cfg["model"], "stream": False, "messages": [{"role": "user", "content": text, "images": [img_b64]}]}, timeout=self.cfg["timeout"])
                    return r["message"]["content"].strip(), f"ollama:{self.cfg['model']}"
                if prov == "openai" and self.cfg.get("openai_model"):
                    r = self._post(self.cfg["openai_url"].rstrip("/") + "/chat/completions", {"model": self.cfg["openai_model"], "messages": [{"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img_b64}}]}]}, timeout=self.cfg["timeout"])
                    return r["choices"][0]["message"]["content"].strip(), f"openai:{self.cfg['openai_model']}"
                if prov == "anthropic" and self.cfg.get("allow_cloud") and os.environ.get("ANTHROPIC_API_KEY"):
                    r = self._post("https://api.anthropic.com/v1/messages", {"model": self.cfg["anthropic_model"], "max_tokens": 1500, "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}}, {"type": "text", "text": text}]}]},
                        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, timeout=self.cfg["timeout"])
                    return "".join(b.get("text", "") for b in r.get("content", [])).strip(), f"anthropic:{self.cfg['anthropic_model']}"
                if prov == "tesseract" and mode == "ocr":
                    pt = _opt("pytesseract")
                    if pt is not None and Image is not None:
                        return pt.image_to_string(Image.open(io.BytesIO(base64.b64decode(img_b64)))).strip(), "tesseract"
            except Exception as e:
                errs.append(f"{prov}: {e}")
        raise RuntimeError("no VLM answered — " + ("; ".join(errs) if errs else "configure vlm.chain in ~/.tabula/config.json"))


class OBSClient:
    """Minimal obs-websocket v5 client (OBS ≥ 28, port 4455)."""

    def __init__(self, url, password, on_state: Callable):
        self.url, self.password, self.on_state = url, password, on_state
        self.ws, self.pending, self.seq = None, {}, 0
        self.scenes, self.current, self.connected = [], None, False

    async def run(self):
        from websockets.asyncio.client import connect  # type: ignore
        while True:
            try:
                async with connect(self.url, subprotocols=["obswebsocket.json"], open_timeout=3) as ws:
                    hello = json.loads(await ws.recv())
                    ident = {"rpcVersion": 1, "eventSubscriptions": 4}                    # Scenes
                    auth = hello["d"].get("authentication")
                    if auth:
                        secret = base64.b64encode(hashlib.sha256((self.password + auth["salt"]).encode()).digest()).decode()
                        ident["authentication"] = base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
                    await ws.send(json.dumps({"op": 1, "d": ident}))
                    self.ws = ws
                    async for raw in ws:
                        m = json.loads(raw)
                        if m["op"] == 2:
                            self.connected = True
                            asyncio.ensure_future(self.refresh())
                        elif m["op"] == 7:
                            f = self.pending.pop(m["d"]["requestId"], None)
                            if f and not f.done():
                                f.set_result(m["d"])
                        elif m["op"] == 5 and m["d"].get("eventType") in ("CurrentProgramSceneChanged", "SceneListChanged"):
                            asyncio.ensure_future(self.refresh())
            except Exception as e:
                if self.connected:
                    log.info("OBS disconnected: %s", e)
                self.connected, self.ws = False, None
                self.on_state(self.state())
            await asyncio.sleep(5)

    def state(self):
        return {"t": "obs", "connected": self.connected, "scenes": self.scenes, "current": self.current}

    async def request(self, rtype, data=None, timeout=4):
        if not self.ws:
            raise RuntimeError("OBS not connected (enable Tools → WebSocket Server Settings)")
        self.seq += 1
        rid = f"tabula{self.seq}"
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.ws.send(json.dumps({"op": 6, "d": {"requestType": rtype, "requestId": rid, "requestData": data or {}}}))
        res = await asyncio.wait_for(fut, timeout)
        st = res.get("requestStatus", {})
        if not st.get("result"):
            raise RuntimeError(f"OBS {rtype}: {st.get('comment') or st.get('code')}")
        return res.get("responseData") or {}

    async def refresh(self):
        try:
            d = await self.request("GetSceneList")
            self.scenes = [s["sceneName"] for s in reversed(d.get("scenes", []))]
            self.current = d.get("currentProgramSceneName")
        except Exception as e:
            log.debug("OBS refresh: %s", e)
        self.on_state(self.state())

    async def act(self, req, data=None):
        data = data or {}
        if req == "ToggleStudioMode":
            on = (await self.request("GetStudioModeEnabled")).get("studioModeEnabled")
            return await self.request("SetStudioModeEnabled", {"studioModeEnabled": not on})
        if req == "NudgeInputVolume":
            v = (await self.request("GetInputVolume", {"inputName": data["inputName"]})).get("inputVolumeDb", 0)
            return await self.request("SetInputVolume", {"inputName": data["inputName"], "inputVolumeDb": max(-100.0, min(26.0, v + data.get("db", 1)))})
        if req in ("NextScene", "PrevScene"):
            await self.refresh()
            if not self.scenes:
                return {}
            i = self.scenes.index(self.current) if self.current in self.scenes else 0
            i = (i + (1 if req == "NextScene" else -1)) % len(self.scenes)
            return await self.request("SetCurrentProgramScene", {"sceneName": self.scenes[i]})
        return await self.request(req, data)


class MidiOut:
    def __init__(self, name):
        self.port, self.err = None, None
        mido = _opt("mido")
        if mido is None:
            self.err = "mido not installed"
            return
        try:
            if OS != "win":
                self.port = mido.open_output(name, virtual=True)                  # appears as a MIDI source named TABULA
            else:
                names = [n for n in mido.get_output_names() if name.lower() in n.lower()]
                self.port = mido.open_output(names[0]) if names else None
                if not self.port:
                    self.err = f"no output port containing '{name}' (create one with loopMIDI / Windows MIDI Services)"
        except Exception as e:
            self.err = str(e)

    def send(self, data):
        if not self.port:
            raise RuntimeError(self.err or "no MIDI port")
        mido = _opt("mido")
        self.port.send(mido.Message.from_bytes(list(data)))


class OSCOut:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, host, port, packet: bytes):
        self.sock.sendto(packet, (host, int(port)))


class Telemetry:
    def __init__(self, ollama_url):
        self.ollama_url = ollama_url
        self.gpus, self.ollama, self._net, self._t = [], [], None, None
        self._stop = False
        threading.Thread(target=self._slow, daemon=True).start()
        if psutil:
            psutil.cpu_percent(None)

    def _slow(self):
        while not self._stop:
            if shutil.which("nvidia-smi"):
                out = _run(["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"], timeout=3)
                g = []
                for line in out.strip().splitlines():
                    p = [x.strip() for x in line.split(",")]
                    if len(p) >= 7:
                        f = lambda v: float(v) if re.fullmatch(r"-?\d+(\.\d+)?", v) else 0.0
                        g.append({"index": int(f(p[0])), "name": p[1], "util": f(p[2]), "memUsed": f(p[3]) / 1024, "memTotal": f(p[4]) / 1024, "temp": f(p[5]), "power": f(p[6])})
                self.gpus = g
            try:
                with urllib.request.urlopen(self.ollama_url.rstrip("/") + "/api/ps", timeout=1.5) as r:
                    d = json.loads(r.read().decode())
                self.ollama = [{"name": m.get("name"), "vram": m.get("size_vram", m.get("size", 0))} for m in d.get("models", [])]
            except Exception:
                self.ollama = []
            time.sleep(2.5)

    def sample(self) -> dict:
        m = {"t": "telemetry", "gpus": self.gpus, "ollama": self.ollama}
        if psutil:
            m["cpu"] = psutil.cpu_percent(None)
            vm = psutil.virtual_memory()
            m["mem"] = {"used": round(vm.used / 1e9, 2), "total": round(vm.total / 1e9, 1)}
            n, now = psutil.net_io_counters(), time.time()
            if self._net and now > self._t:
                m["net"] = {"rx": (n.bytes_recv - self._net.bytes_recv) / (now - self._t), "tx": (n.bytes_sent - self._net.bytes_sent) / (now - self._t)}
            self._net, self._t = n, now
        else:
            m["cpu"] = 0.0
        return m


# ==================================================================================================
# sensing: depth sources → touch engine; IR light plane; ArUco tangibles; TUIO in; tap calibration
# ==================================================================================================
class DepthSource:
    """Yields (depth_mm float32 HxW with 0 = invalid, timestamp). Subclasses wrap vendor SDKs."""
    name = "base"
    desk_aligned = False            # True when the image already spans the desk (synthetic)

    def open(self): ...
    def read(self): raise NotImplementedError
    def close(self): ...


class SyntheticDepth(DepthSource):
    """A desk at 800 mm with sensor noise, a mug, a phone, and 1–2 arms whose index fingers tap on a schedule.
    `truth` exposes the true fingertip (u, v, z_mm) so the engine can be tested end-to-end."""
    name = "synthetic"
    desk_aligned = True

    def __init__(self, w=320, h=180, desk_mm=(1000.0, 562.5), hz=30, seed=3, arms=2):
        self.w, self.h, self.desk, self.hz, self.arms = w, h, desk_mm, hz, arms
        self.rng = np.random.default_rng(seed)
        self.t0 = time.time()
        self.frame_i = 0
        self.truth = []
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.X = (xx + 0.5) / w * desk_mm[0]
        self.Y = (yy + 0.5) / h * desk_mm[1]
        self.base = 800.0 + (self.X - desk_mm[0] / 2) * 0.004 - (self.Y - desk_mm[1] / 2) * 0.003     # slightly tilted desk

    def finger_state(self, t, k):
        """deterministic choreography: finger k glides along a path and taps every ~1.6 s"""
        W, H = self.desk
        cx = W * (0.3 + 0.4 * k) + W * 0.12 * math.sin(0.7 * t + k)
        cy = H * 0.45 + H * 0.15 * math.cos(0.9 * t + 2 * k)
        ph = ((t + 0.8 * k) % 1.6) / 1.6
        z = 6.0 if 0.35 < ph < 0.65 else 45.0                        # touching for ~0.48 s per cycle
        return cx, cy, z

    def read(self):
        t = self.frame_i / self.hz
        self.frame_i += 1
        W, H = self.desk
        hmap = np.zeros_like(self.X)
        self.truth = []
        if self.frame_i <= 30:                                                                  # empty desk first: the engine learns its background
            depth = self.base + self.rng.normal(0, 1.4, hmap.shape).astype(np.float32)
            return depth.astype(np.float32), time.time()
        hmap = np.maximum(hmap, np.where((self.X - W * 0.86) ** 2 + (self.Y - H * 0.25) ** 2 < 40 ** 2, 95.0, 0.0))          # mug
        hmap = np.maximum(hmap, np.where((np.abs(self.X - W * 0.12) < 37) & (np.abs(self.Y - H * 0.3) < 77), 8.0, 0.0))     # phone
        for k in range(self.arms):
            fx, fy, fz = self.finger_state(t, k)
            self.truth.append((fx / W, fy / H, fz))
            ex, ey = fx + (180 if k else -180) * 0.6, H + 60                                  # elbow off the near edge
            vx, vy = fx - ex, fy - ey
            L = math.hypot(vx, vy)
            ux, uy = vx / L, vy / L
            px, py = self.X - ex, self.Y - ey
            a = L - (px * ux + py * uy)                                                         # from the fingertip back toward the elbow
            b = (px * uy - py * ux) * (1.0 if k else -1.0)                                      # across, + toward the thumb (arm 1 is a right arm)
            # a hand pointing with the INDEX finger: the finger leaves the fist at its thumb-side edge (thumb folded under),
            # and the middle, ring and little fingers are curled into three high knuckles that never reach the touch band
            fin = (a >= 0) & (a < 75) & (np.abs(b) < 8.5)                                       # index finger, 75 mm
            taper = np.clip((a - 75) / 100.0, 0, 1)
            hand = (a >= 75) & (a < 175) & (b < 16 + 15 * taper) & (b > -62 + 17 * taper)
            front = 60.0 - 2.5 * np.cos(2 * math.pi * (b + 19.5) / 17.0)                      # three curled knuckles: a shallow scallop,
            curl = (a >= front) & (a < 75) & (b > -62) & (b < -11)                             # too blunt to read as fingertips
            fore = (a >= 175) & (np.abs(b + 7) < 38)
            finger_h = fz + (55.0 - fz) * np.clip(a / 75.0, 0, 1)                              # slopes continuously up into the hand
            hmap = np.where(fin, np.maximum(hmap, finger_h), hmap)
            hmap = np.where(curl, np.maximum(hmap, 50.0), hmap)
            hmap = np.where(hand, np.maximum(hmap, 55.0), hmap)
            hmap = np.where(fore, np.maximum(hmap, 75.0), hmap)
        depth = self.base - hmap + self.rng.normal(0, 1.4, hmap.shape).astype(np.float32)
        depth[self.rng.random(depth.shape) < 0.004] = 0                                         # dropouts
        return depth.astype(np.float32), time.time()


class RealSenseDepth(DepthSource):
    name = "realsense"

    def open(self):
        import pyrealsense2 as rs  # type: ignore
        self.rs = rs
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 60)
        prof = self.pipe.start(cfg)
        self.scale = prof.get_device().first_depth_sensor().get_depth_scale() * 1000.0             # → mm
        self.spatial, self.temporal = rs.spatial_filter(), rs.temporal_filter()

    def read(self):
        f = self.pipe.wait_for_frames(1000).get_depth_frame()
        f = self.temporal.process(self.spatial.process(f))
        return np.asanyarray(f.get_data()).astype(np.float32) * self.scale, time.time()

    def close(self):
        try:
            self.pipe.stop()
        except Exception:
            pass


class OrbbecDepth(DepthSource):
    name = "orbbec"

    def open(self):
        from pyorbbecsdk import Pipeline, Config, OBSensorType  # type: ignore  (pip install pyorbbecsdk2)
        self.pipe, cfg = Pipeline(), Config()
        prof = self.pipe.get_stream_profile_list(OBSensorType.DEPTH_SENSOR).get_default_video_stream_profile()
        cfg.enable_stream(prof)
        self.pipe.start(cfg)

    def read(self):
        while True:
            fs = self.pipe.wait_for_frames(200)
            d = fs.get_depth_frame() if fs else None
            if d is not None:
                arr = np.frombuffer(d.get_data(), dtype=np.uint16).reshape(d.get_height(), d.get_width()).astype(np.float32)
                return arr * float(d.get_depth_scale()), time.time()

    def close(self):
        try:
            self.pipe.stop()
        except Exception:
            pass


class K4ADepth(DepthSource):
    """Azure Kinect, or Orbbec Femto Bolt/Mega through Orbbec's K4A wrapper."""
    name = "k4a"

    def open(self):
        from pyk4a import PyK4A, Config, DepthMode, ColorResolution, FPS  # type: ignore
        self.k = PyK4A(Config(color_resolution=ColorResolution.OFF, depth_mode=DepthMode.NFOV_UNBINNED, camera_fps=FPS.FPS_30))
        self.k.start()

    def read(self):
        return self.k.get_capture().depth.astype(np.float32), time.time()

    def close(self):
        try:
            self.k.stop()
        except Exception:
            pass


class Freenect2Depth(DepthSource):
    name = "freenect2"

    def open(self):
        from pylibfreenect2 import Freenect2, SyncMultiFrameListener, FrameType, CpuPacketPipeline  # type: ignore
        self.fn = Freenect2()
        self.dev = self.fn.openDevice(self.fn.getDeviceSerialNumber(0), pipeline=CpuPacketPipeline())
        self.lst = SyncMultiFrameListener(FrameType.Depth)
        self.dev.setIrAndDepthFrameListener(self.lst)
        self.dev.startStreams(rgb=False, depth=True)

    def read(self):
        fr = self.lst.waitForNewFrame()
        d = fr["depth"].asarray().copy()
        self.lst.release(fr)
        return d.astype(np.float32), time.time()

    def close(self):
        try:
            self.dev.stop(); self.dev.close()
        except Exception:
            pass


class ReplayDepth(DepthSource):
    name = "replay"

    def __init__(self, path):
        self.frames = np.load(path)["depth"]
        self.i = 0

    def read(self):
        f = self.frames[self.i % len(self.frames)]
        self.i += 1
        time.sleep(1 / 30)
        return f.astype(np.float32), time.time()


def make_depth(src: str) -> DepthSource:
    s = src.lower()
    if s == "synthetic":
        return SyntheticDepth()
    if s.startswith("replay:"):
        return ReplayDepth(src.split(":", 1)[1])
    return {"realsense": RealSenseDepth, "orbbec": OrbbecDepth, "k4a": K4ADepth, "femto": K4ADepth, "freenect2": Freenect2Depth, "kinect2": Freenect2Depth}[s]()


# -------------------------------- the touch engine --------------------------------
class Track:
    __slots__ = ("id", "u", "v", "raw", "z", "down", "cnt_on", "cnt_off", "age", "fx", "fy", "seen")

    def __init__(self, tid, euro):
        self.id, self.down, self.cnt_on, self.cnt_off, self.age, self.seen = tid, False, 0, 0, 0, True
        self.u = self.v = self.z = 0.0
        self.raw = (0.0, 0.0)
        self.fx, self.fy = OneEuro(euro["min_cutoff"], euro["beta"], euro["d_cutoff"]), OneEuro(euro["min_cutoff"], euro["beta"], euro["d_cutoff"])


class TouchEngine:
    """Depth → contacts.
    Wilson (ITS 2010): per-pixel background, touch = thin height band above the surface.
    DIRECT (ISS 2016): fingers belong to an arm that enters from the frame edge; the tip is the geodesically farthest
    point from that edge; contact uses hysteresis; a rolling background absorbs things that stay still."""

    def __init__(self, cfg: dict, desk_mm=(1000.0, 562.5), sensor_h_mm=800.0):
        if cv2 is None or np is None:
            raise RuntimeError("the depth touch engine needs numpy + opencv")
        self.c = cfg
        self.desk = desk_mm
        self.sensor_h = sensor_h_mm
        self.bg = None
        self.bg0 = None
        self.sigma = None
        self.learn = []
        self.tracks: dict = {}
        self.next_id = 1
        self.H = None                 # raw px → desk normalised
        self.shape = None
        self.stats = {"frames": 0, "ms": 0.0, "contacts": 0}
        self.still_since = None

    # --- geometry helpers ---
    def band(self):
        h = self.sensor_h
        lo = self.c["band_lo"] if self.c["band_lo"] is not None else max(3.0, 3.0 + (h - 750) * 3 / 750)
        hi = self.c["band_hi"] if self.c["band_hi"] is not None else 14.0 + (h - 750) * 16 / 750
        return lo, hi

    def to_desk(self, x, y):
        if self.H is not None:
            return h_apply(self.H, x, y)
        H, W = self.shape
        return x / W, y / H

    def mm_per_px(self):
        H, W = self.shape
        a = self.to_desk(W / 2, H / 2)
        b = self.to_desk(W / 2 + 1, H / 2)
        c = self.to_desk(W / 2, H / 2 + 1)
        return math.sqrt(abs((b[0] - a[0]) * self.desk[0] * (c[1] - a[1]) * self.desk[1] - (b[1] - a[1]) * self.desk[1] * (c[0] - a[0]) * self.desk[0]))

    def relearn(self):
        self.bg = None
        self.bg0 = None
        self.learn = []

    # --- main step ---
    def step(self, depth_full, t):
        t0 = time.perf_counter()
        k = max(1, int(self.c["downsample"]))
        Hh, Ww = depth_full.shape[0] // k, depth_full.shape[1] // k
        d = depth_full[:Hh * k, :Ww * k].reshape(Hh, k, Ww, k)
        valid = d > 0
        cnt = valid.sum((1, 3))
        ds = np.where(cnt > 0, (d * valid).sum((1, 3)) / np.maximum(cnt, 1), 0).astype(np.float32)
        self.shape = (depth_full.shape[0], depth_full.shape[1])
        if self.bg is None:
            self.learn.append(ds)
            if len(self.learn) >= 24:
                st = np.stack(self.learn)
                st = np.where(st > 0, st, np.nan)
                self.bg = np.nan_to_num(np.nanmedian(st, 0), nan=0.0).astype(np.float32)
                mad = np.nan_to_num(np.nanmedian(np.abs(st - self.bg), 0), nan=5.0)
                self.sigma = np.clip(mad * 1.4826, 0.5, 8.0).astype(np.float32)
                self.bg0 = self.bg.copy()
                self.learn = []
                log.info("depth background learned (median σ %.2f mm)", float(np.median(self.sigma)))
            return None
        lo, hi = self.band()
        hmap = np.where((ds > 0) & (self.bg > 0), self.bg - ds, 0).astype(np.float32)
        thr = np.maximum(lo, 3 * self.sigma)
        above = (hmap > thr).astype(np.uint8)                        # no morphological opening: a 17 mm finger is only ~3 px wide here
        n, lab, stats, cents = cv2.connectedComponentsWithStats(above, connectivity=8)
        mmpp = self.mm_per_px() * k
        tips, hands, heads, objects, palm = [], [], [], [], False
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < self.c["min_blob_px"]:
                continue
            sub = lab[y:y + h, x:x + w] == i
            hs = hmap[y:y + h, x:x + w]
            hmax = float(hs[sub].max())
            border = x == 0 or y == 0 or x + w >= Ww or y + h >= Hh
            if hmax >= self.c["head_mm"]:
                cx, cy = cents[i]
                u, v = self.to_desk((cx + 0.5) * k, (cy + 0.5) * k)
                heads.append({"x": u, "y": v, "r": 0.5 * math.sqrt(area) * mmpp / self.desk[0]})
                continue
            if border and hmax >= self.c["arm_mm"]:
                contact_area = float(((hs <= hi) & sub).sum()) * mmpp * mmpp
                if contact_area > self.c["palm_area_mm2"]:
                    palm = True
                tips += self._tips(sub, hs, x, y, k, mmpp, hi, Ww, Hh)
                cnts, _ = cv2.findContours(sub.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if cnts:
                    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))[:, 0, :]
                    hands.append([list(self.to_desk((px + x + 0.5) * k, (py + y + 0.5) * k)) for px, py in hull[:: max(1, len(hull) // 24)]])
            elif not border:
                u0, v0 = self.to_desk((x + 0.5) * k, (y + 0.5) * k)
                u1, v1 = self.to_desk((x + w + 0.5) * k, (y + h + 0.5) * k)
                objects.append({"kind": "object", "x": (u0 + u1) / 2, "y": (v0 + v1) / 2, "w": abs(u1 - u0), "h": abs(v1 - v0), "hmax": round(hmax, 1)})
        contacts = self._track(tips, t, lo, hi)
        self._roll_bg(ds, hmap, lo, t, bool(tips))
        self.stats = {"frames": self.stats["frames"] + 1, "ms": round((time.perf_counter() - t0) * 1000, 2), "contacts": sum(1 for c in contacts if c["phase"] != "hover"),
                      "band_mm": [round(lo, 1), round(hi, 1)], "sigma_mm": round(float(np.median(self.sigma)), 2)}
        return {"contacts": contacts, "hands": hands, "heads": heads, "objects": objects, "palm": palm}

    def _tips(self, sub, hs, ox, oy, k, mmpp, hi, Ww, Hh):
        """geodesic distance from the arm's entry pixels; tips = local maxima of that distance"""
        h, w = sub.shape
        D = np.full(sub.shape, -1, np.int32)
        seed = np.zeros_like(sub)
        if oy == 0: seed[0, :] = sub[0, :]
        if ox == 0: seed[:, 0] |= sub[:, 0]
        if oy + h >= Hh: seed[-1, :] |= sub[-1, :]
        if ox + w >= Ww: seed[:, -1] |= sub[:, -1]
        # geodesic distance from the entry edge, propagating only between pixels of similar height, so a flood never
        # jumps from an arm onto a phone or book lying under it (height continuity stands in for DIRECT's IR edges)
        jump = self.c.get("jump_mm", 30.0)
        up = np.abs(hs[:-1, :] - hs[1:, :]) < jump
        lf = np.abs(hs[:, :-1] - hs[:, 1:]) < jump
        front = seed.copy()
        D[front] = 0
        dist = 0
        while front.any() and dist < 2000:
            dist += 1
            nxt = np.zeros_like(front)
            nxt[:-1, :] |= front[1:, :] & up
            nxt[1:, :] |= front[:-1, :] & up
            nxt[:, :-1] |= front[:, 1:] & lf
            nxt[:, 1:] |= front[:, :-1] & lf
            nxt &= sub & (D < 0)
            D[nxt] = dist
            front = nxt
        if D.max() <= 0:
            return []
        Df = D.astype(np.float32)
        loc = (D > 0) & (Df >= cv2.dilate(Df, np.ones((5, 5), np.uint8))) & (Df >= 0.55 * Df.max()) & (Df * mmpp >= 60)
        ys, xs = np.nonzero(loc)
        order = np.argsort(-Df[ys, xs])
        sep = self.c["tip_sep_mm"] / mmpp
        tips = []
        r_px = max(1.5, 7.0 / mmpp)
        pad = self.c.get("pad_mm", 5.0) / mmpp                         # fingerpad sits ~5 mm behind the extremal point
        for j in order:
            px, py = xs[j], ys[j]
            if any(math.hypot(px - q[0], py - q[1]) < sep for q in tips):
                continue
            tips.append((px, py))
            if len(tips) >= 5:
                break
        out = []
        for rank, (px, py) in enumerate(tips):
            dtip = D[py, px]
            yy, xx = np.ogrid[:h, :w]
            reg = sub & (D >= dtip - r_px) & ((xx - px) ** 2 + (yy - py) ** 2 <= (2 * r_px) ** 2)
            zs = hs[reg]
            if zs.size == 0:
                continue
            z = float(np.median(zs))
            ry, rx = np.nonzero(reg)
            ax, ay = px - rx.mean(), py - ry.mean()                    # finger direction: region centroid → extremal pixel
            n = math.hypot(ax, ay) or 1.0
            cx, cy = px - ax / n * pad, py - ay / n * pad
            if rank > 0:
                # extra extremities only count when they are fingers: low at the tip AND still low a finger-width inward.
                # The rim of a fist, a knuckle or the edge of a hand is depth-mixed with the desk (ToF/stereo "flying
                # pixels", and our own down-sampling), so its outermost pixels can read touch-low while it rises at once.
                near = sub & ((xx - px) ** 2 + (yy - py) ** 2 <= (2 * r_px) ** 2)                 # a fingertip-sized disc
                z_near = float(np.percentile(hs[near], 75)) if near.any() else z
                if z > hi * 1.5 or z_near > hi * 2.5:
                    continue
            rawx, rawy = (ox + cx + 0.5) * k, (oy + cy + 0.5) * k
            u, v = self.to_desk(rawx, rawy)
            out.append({"u": u, "v": v, "z": z, "raw": (rawx, rawy)})
        return out

    def _track(self, tips, t, lo, hi):
        euro = self.c["euro"]
        W, H = self.desk
        for tr in self.tracks.values():
            tr.seen = False
        maxj = self.c["max_jump_mm"]
        pairs = sorted(((math.hypot((tp["u"] - tr.u) * W, (tp["v"] - tr.v) * H), i, tr.id) for i, tp in enumerate(tips) for tr in self.tracks.values()))
        used_t, used_p = set(), set()
        for dmm, i, tid in pairs:
            if dmm > maxj or i in used_p or tid in used_t:
                continue
            used_p.add(i); used_t.add(tid)
            self._update(self.tracks[tid], tips[i], t)
        for i, tp in enumerate(tips):
            if i not in used_p:
                tr = Track(self.next_id, euro)
                self.next_id += 1
                self.tracks[tr.id] = tr
                self._update(tr, tp, t)
        out = []
        for tid, tr in list(self.tracks.items()):
            if not tr.seen:
                tr.cnt_off += 1
                if tr.down and tr.cnt_off >= self.c["up_frames"]:
                    out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "up"})
                    tr.down = False
                if tr.cnt_off > 4:
                    del self.tracks[tid]
                continue
            touching = tr.z <= (hi if tr.down else hi - 2.0)             # hysteresis: easier to stay down than to go down
            if touching:
                tr.cnt_on += 1
                tr.cnt_off = 0
            else:
                tr.cnt_off += 1
                tr.cnt_on = 0
            if not tr.down and tr.cnt_on >= self.c["down_frames"]:
                tr.down = True
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "down"})
            elif tr.down and tr.cnt_off >= self.c["up_frames"]:
                tr.down = False
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "up"})
            elif tr.down:
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "move"})
            elif tr.z <= self.c["hover_mm"]:
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "hover"})
        return out

    def _update(self, tr, tp, t):
        W, H = self.desk
        tr.u = tr.fx(tp["u"] * W, t) / W
        tr.v = tr.fy(tp["v"] * H, t) / H
        tr.z, tr.raw, tr.seen = tp["z"], tp["raw"], True
        tr.age += 1

    def _roll_bg(self, ds, hmap, lo, t, active):
        """slow update where the surface is quiet; absorb objects that stay still for stun_s (not while a hand is present)"""
        quiet = (np.abs(hmap) < lo) & (ds > 0)
        self.bg[quiet] = self.bg[quiet] * 0.98 + ds[quiet] * 0.02
        if active:
            self.still_since = None
            return
        if self.still_since is None:
            self.still_since = t
        elif t - self.still_since > self.c["stun_s"]:
            placed = (hmap > lo) & (hmap < self.c["arm_mm"]) & (ds > 0)
            self.bg[placed] = ds[placed]
            self.still_since = t


class LightPlane:
    """IR light curtain: a Class-1 850 nm line laser 1–2 mm above the desk; an IR-pass camera sees fingertips as bright blobs."""

    def __init__(self, index: int, thresh=200):
        self.cap = cv2.VideoCapture(index)
        self.thresh = thresh
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} not available")

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            return None, None
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, b = cv2.threshold(cv2.GaussianBlur(g, (5, 5), 0), self.thresh, 255, cv2.THRESH_BINARY)
        n, lab, st, cen = cv2.connectedComponentsWithStats(b, connectivity=8)
        pts = [(float(cen[i][0]), float(cen[i][1])) for i in range(1, n) if 12 <= st[i][4] <= 4000]
        return pts, g.shape

    def close(self):
        self.cap.release()


class Tangibles:
    """ArUco MIP 36h12 tokens (same dictionary as js-aruco2 in the page). Markers 0–3 placed on the projected image
    corners calibrate the camera automatically; every other id is reported as a token with position + rotation."""

    def __init__(self, index: int, corner_ids=(0, 1, 2, 3)):
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} not available")
        self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12), cv2.aruco.DetectorParameters())
        self.corner_ids = list(corner_ids)
        self.H = None
        self.last = None
        self.lock = threading.Lock()                           # one reader at a time: sensing thread vs. Gray-code capture

    def grab(self):
        with self.lock:
            ok, frame = self.cap.read()
        return frame if ok else None

    def read(self):
        frame = self.grab()
        if frame is None:
            return None
        self.last = frame
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.det.detectMarkers(g)
        found = {}
        if ids is not None:
            for c, i in zip(corners, ids.ravel()):
                found[int(i)] = c[0]
        if all(i in found for i in self.corner_ids):
            src = [tuple(found[i].mean(0)) for i in self.corner_ids]
            H = homography_dlt(src, [(0, 0), (1, 0), (1, 1), (0, 1)])
            if H is not None:
                self.H = H
        toks = []
        if self.H is not None:
            for i, c in found.items():
                if i in self.corner_ids:
                    continue
                pts = [h_apply(self.H, float(x), float(y)) for x, y in c]
                cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
                ang = math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
                toks.append({"kind": "token", "id": i, "x": cx, "y": cy, "angle": ang, "w": abs(pts[1][0] - pts[0][0]) + 0.01, "h": abs(pts[3][1] - pts[0][1]) + 0.01})
        return {"tokens": toks, "calibrated": self.H is not None, "seen": sorted(found)}

    def close(self):
        with self.lock:
            self.cap.release()


def marker_sheet_svg(ids=range(0, 24), size_mm=35.0, cols=4) -> str:
    """Printable true-scale sheet of ArUco MIP 36h12 markers (0–3 = desk corners)."""
    if cv2 is None:
        raise RuntimeError("needs opencv-contrib-python")
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)
    cell = size_mm + 20
    rows = math.ceil(len(list(ids)) / cols)
    W, H = cols * cell + 20, rows * cell + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">', f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<text x="10" y="12" font-family="sans-serif" font-size="5">TABULA-Ω tokens · ArUco MIP 36h12 · {size_mm:.0f} mm · print at 100 % · 0–3 go on the projected image corners (TL, TR, BR, BL)</text>']
    for n, mid in enumerate(ids):
        img = cv2.aruco.generateImageMarker(d, int(mid), 8)                         # 6×6 bits + 1-cell border = 8 cells, 1 px each
        px = size_mm / 8
        ox, oy = 10 + (n % cols) * cell, 20 + (n // cols) * cell
        out.append(f'<g transform="translate({ox},{oy})">')
        for y in range(8):
            for x in range(8):
                if img[y, x] < 128:
                    out.append(f'<rect x="{x * px:.3f}" y="{y * px:.3f}" width="{px + 0.01:.3f}" height="{px + 0.01:.3f}" fill="black"/>')
        label = {0: "corner TL", 1: "corner TR", 2: "corner BR", 3: "corner BL"}.get(mid, f"id {mid}")
        out.append(f'<text x="0" y="{size_mm + 6}" font-family="sans-serif" font-size="4">{label}</text></g>')
    out.append("</svg>")
    return "\n".join(out)


class TapCal:
    """Generic raw-sensor → desk calibration: the page shows 9 rings; the user touches each and holds still."""
    TARGETS = [(fx, fy) for fy in (0.2, 0.52, 0.84) for fx in (0.1, 0.5, 0.9)]

    LIFT_FRAMES = 3                                            # the finger must leave the surface between targets

    def __init__(self):
        self.i, self.samples, self.hold, self.done = 0, [], [], False
        self.need_lift, self.lift = False, 0

    def feed(self, raw_points, t):
        """raw_points: list of (x, y) touching points this frame → returns 'next' when a target was captured"""
        if self.done:
            return None
        if self.need_lift:                                     # a finger still resting on the last ring must not become the next sample
            self.lift = self.lift + 1 if not raw_points else 0
            if self.lift >= self.LIFT_FRAMES:
                self.need_lift = False
            return None
        if len(raw_points) != 1:
            self.hold = []
            return None
        p = raw_points[0]
        if self.hold and math.dist(self.hold[0][1], p) > 6:
            self.hold = []
        self.hold.append((t, p))
        if t - self.hold[0][0] >= 0.6:
            xs = [q[1][0] for q in self.hold]
            ys = [q[1][1] for q in self.hold]
            self.samples.append(((sum(xs) / len(xs), sum(ys) / len(ys)), self.TARGETS[self.i]))
            self.hold, self.i = [], self.i + 1
            self.need_lift, self.lift = True, 0
            if self.i >= len(self.TARGETS):
                self.done = True
            return "next"
        return None

    def solve(self):
        H, idx, rms = homography_ransac([s[0] for s in self.samples], [s[1] for s in self.samples], thresh=0.02)
        return H, rms, len(idx)


class TUIOIn:
    """Listens for TUIO 1.1 (/tuio/2Dcur, /tuio/2Dobj) — lets any external tracker (reacTIVision, CCV, OAK-D apps…) drive the desk."""

    def __init__(self, port=3333):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.5)
        self.cur, self.obj = {}, {}

    def poll(self):
        try:
            data, _ = self.sock.recvfrom(65536)
        except socket.timeout:
            return None
        except OSError:                                        # closed by stop_sense
            return None
        try:
            msgs = osc_parse(data)
        except Exception:                                      # one malformed datagram must not kill the listener
            return True
        for addr, args in msgs:
            try:
                if not args:
                    continue
                if addr == "/tuio/2Dcur":
                    if args[0] == "alive":
                        alive = set(args[1:])
                        self.cur = {k: v for k, v in self.cur.items() if k in alive}
                    elif args[0] == "set" and len(args) >= 4:
                        x, y = float(args[2]), float(args[3])
                        if math.isfinite(x) and math.isfinite(y):
                            self.cur[args[1]] = (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))
                elif addr == "/tuio/2Dobj":
                    if args[0] == "alive":
                        alive = set(args[1:])
                        self.obj = {k: v for k, v in self.obj.items() if k in alive}
                    elif args[0] == "set" and len(args) >= 6:
                        x, y, a = float(args[3]), float(args[4]), float(args[5])
                        if math.isfinite(x) and math.isfinite(y) and math.isfinite(a):
                            self.obj[args[1]] = (int(args[2]), min(1.0, max(0.0, x)), min(1.0, max(0.0, y)), a)
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        return True

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def tuio_frame(contacts, fseq, source="tabula@localhost") -> bytes:
    msgs = [osc_message("/tuio/2Dcur", "source", source), osc_message("/tuio/2Dcur", "alive", *[int(c["id"]) for c in contacts])]
    for c in contacts:
        msgs.append(osc_message("/tuio/2Dcur", "set", int(c["id"]), float(c["x"]), float(c["y"]), 0.0, 0.0, 0.0))
    msgs.append(osc_message("/tuio/2Dcur", "fseq", int(fseq)))
    return osc_bundle(*msgs)


# ==================================================================================================
# the host: WebSocket + HTTP server, safety gate, dispatch
# ==================================================================================================
class Bucket:
    def __init__(self, rate):
        self.rate, self.tokens, self.t = float(rate), float(rate), time.monotonic()

    def take(self, n=1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.rate, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


def _finite(o):
    """JSON without NaN/Infinity (the browser's JSON.parse rejects them)"""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def _dumps(obj) -> str:
    try:
        return json.dumps(obj, default=str, allow_nan=False)
    except ValueError:
        return json.dumps(_finite(obj), default=str, allow_nan=False)


class Client:
    """One browser window. Everything sent to it goes through a bounded outbound queue drained by its own writer
    task, so a window that stops reading (sleeping laptop, frozen tab, lost Wi-Fi) can never block the reader of
    another window — PANIC included. A send that stalls for SEND_TIMEOUT s, or a queue that overflows, drops it."""
    MAX_OUT, SEND_TIMEOUT = 600, 4.0

    def __init__(self, ws):
        self.ws, self.role, self.portal = ws, "?", None
        self.addr = getattr(ws, "remote_address", None)
        self.q_act: asyncio.Queue = asyncio.Queue()           # act / window ops / clipboard writes, in order
        self.q_ptr: asyncio.Queue = asyncio.Queue()           # pointer + touch frames, in order
        self.tasks: set = set()                                # slow requests (VLM, scan, sensing) run beside the reader
        self.out: collections.deque = collections.deque()
        self.out_ev = asyncio.Event()
        self.frames = 0                                        # PORTAL frames queued but not yet written
        self.dead = False
        self.last_seen = time.time()

    def send_nowait(self, obj, frame=False) -> bool:
        if self.dead:
            return False
        if frame and self.frames >= 2:
            return False                                       # the window is behind: skip this frame
        if len(self.out) >= self.MAX_OUT:
            self.kill("outbound queue overflow")
            return False
        self.out.append((obj, frame))
        if frame:
            self.frames += 1
        self.out_ev.set()
        return True

    async def send(self, obj):                                 # never waits for the socket
        self.send_nowait(obj)

    def kill(self, why):
        if self.dead:
            return
        self.dead = True
        log.warning("dropping a window that stopped reading (%s): %s", why, self.addr)
        tr = getattr(self.ws, "transport", None)
        try:
            if tr is not None:
                tr.abort()                                     # no closing handshake: it would stall too
            else:
                asyncio.ensure_future(self.ws.close())
        except Exception:
            pass

    async def writer(self):
        while not self.dead:
            await self.out_ev.wait()
            self.out_ev.clear()
            while self.out and not self.dead:
                obj, frame = self.out.popleft()
                try:
                    data = obj if isinstance(obj, (bytes, bytearray)) else _dumps(obj)
                    await asyncio.wait_for(self.ws.send(data), self.SEND_TIMEOUT)
                except asyncio.TimeoutError:
                    self.kill(f"a send took longer than {self.SEND_TIMEOUT:.0f} s")
                    return
                except Exception:
                    self.dead = True
                    return
                finally:
                    if frame:
                        self.frames -= 1


def _release_msg(m: dict) -> bool:
    """messages that end an input — never rate-limited or dropped"""
    if m.get("t") == "ptr":
        return m.get("op") == "up"
    if m.get("t") == "touch":
        return any(isinstance(c, dict) and c.get("phase") == "up" for c in (m.get("contacts") or []))
    return False


class Host:
    def __init__(self, args, store: Store):
        self.args, self.store, self.cfg = args, store, store.cfg
        self.plat = Platform()
        raw = make_backend(args.backend, args.dry_run, self.plat.desktop_box(), self.cfg["punctuation"], self.cfg.get("keyboard_layout", "auto"))
        self.dry = isinstance(raw, DryRunBackend)
        self.inp = Guarded(raw, lambda: self.armed)          # serialised, and refused the instant the host disarms
        self.gen = 0                                           # bumps on every disarm; in-flight work checks it between chords/chunks
        self.last_touch = 0.0
        self.sense_lock = threading.Lock()
        self.addrs = local_addresses() if self.cfg["lan"] else set()
        self._page_cache = None
        self.vlm = VLM(self.cfg["vlm"])
        self.telemetry = Telemetry(self.cfg["vlm"]["ollama_url"])
        self.osc = OSCOut()
        self.midi = None
        self.obs = OBSClient(self.cfg["obs"]["url"], self.cfg["obs"]["password"], self._obs_state)
        self.clients: set = set()
        self.armed, self.last_activity, self.buttons_since, self.arm_client = False, time.time(), {}, None
        self.buckets = {k: Bucket(v) for k, v in self.cfg["rate"].items()}
        self.focus, self.clip_hist, self.last_clip = None, collections.deque(maxlen=40), None
        self.sense_thread, self.sense_stop, self.sense_status = None, threading.Event(), {"source": None}
        self.engine, self.tapcal, self.tangibles, self.lightplane, self.tuio_in = None, None, None, None, None
        self.gc_wait = None
        self.fseq = 0
        self.desk = (1000.0, 562.5)
        self.loop = None
        page = HERE / "tabula.html"
        self.page_path = page if page.exists() else (HERE / "dist" / "tabula.html")
        store.audit("start", version=VERSION, backend=self.inp.name, dry=self.dry)

    # ---------------- policy ----------------
    def allowlist_problems(self) -> list:
        out = []
        for name, e in self.cfg["launch"].items():
            why = allowlist_problem(e.get("argv") if isinstance(e, dict) else e)
            if why:
                out.append(f"launch.{name}: {why}")
        for name, r in self.cfg["run"].items():
            why = allowlist_problem((r or {}).get("argv", []))
            if why:
                out.append(f"run.{name}: {why}")
        return out

    def shell_wildcard(self) -> bool:
        return bool(self.allowlist_problems())

    def observe_ok(self) -> bool:
        return bool(self.cfg.get("observe_disarmed", True)) or self.armed

    def audit_info(self):
        lan = bool(self.cfg["lan"])
        return {"bind": "0.0.0.0" if lan else self.cfg["bind"], "lan": lan, "tokenLen": len(self.store.token),
                "tokenDelivery": "URL fragment from the host — never inlined in the page",
                "origins": ("Host + Origin allow-list: this PC's own names and addresses" if lan else "Host + Origin: loopback only")
                           + (" + extra_origins" if self.cfg["extra_origins"] else "") + (" · Origin-less clients allowed" if self.cfg.get("allow_no_origin") else ""),
                "frameAncestors": "none", "inputBinding": "only the window that armed may inject", "allowNoOrigin": bool(self.cfg.get("allow_no_origin")),
                "gate": "advisory — the host checks the report is fresh and unanimous but cannot re-run the page's critics",
                "observeDisarmed": bool(self.cfg.get("observe_disarmed", True)), "idleDisarmS": self.cfg["idle_disarm_s"],
                "shellWildcard": self.shell_wildcard(), "allowlist": self.allowlist_problems()}

    def resolve_argv(self, entry):
        """allow-list entry → (argv with argv[0] resolved on PATH, cwd). Entries are a list or {"argv": [...], "cwd": "..."}."""
        argv, cwd = (entry.get("argv"), entry.get("cwd")) if isinstance(entry, dict) else (entry, None)
        if not isinstance(argv, list) or not argv:
            raise ValueError("allow-list entry has no argv")
        argv = [os.path.expandvars(os.path.expanduser(str(x))) for x in argv]
        if not os.path.isabs(argv[0]):
            found = shutil.which(argv[0])                    # resolves PATHEXT on Windows (code → code.cmd)
            if not found:
                raise FileNotFoundError(f"{argv[0]}: not found on PATH — put the full path in ~/.tabula/config.json")
            argv[0] = found
        return argv, (os.path.expandvars(os.path.expanduser(cwd)) if cwd else None)

    def caps(self):
        c = ["act", "ptr", "win", "clip", "portal", "vlm", "obs", "osc", "midi", "tuio"]
        if "touch" in self.inp.caps:
            c.append("touch")
        if self.cfg["calib"].get("H_desk_cam") and self.tangibles is not None:
            c.append("scan")
        return c

    def welcome(self):
        return {"t": "welcome", "v": 1, "armed": self.armed, "audit": self.audit_info(),
                "host": {"os": OS, "version": VERSION, "input": self.inp.name, "dry": self.dry, "focus": self.plat.focus_via, "capture": "mss" if mss_mod else "synthetic",
                         "sense": self.sense_status.get("source") or "none", "senseStatus": self.sense_status, "screens": self.plat.screens(), "caps": self.caps(),
                         "vlm": self.vlm.describe(), "persistFrames": bool(self.cfg["persist_frames"]), "observe": self.observe_ok()}}

    # ---------------- HTTP side ----------------
    def _resp(self, status, body: bytes, ctype):
        st = http.HTTPStatus(status)
        return Response(st.value, st.phrase, Headers([("Date", email.utils.formatdate(usegmt=True)), ("Connection", "close"), ("Content-Length", str(len(body))),
                                                     ("Content-Type", ctype), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                                                     ("Content-Security-Policy", "frame-ancestors 'none'"), ("X-Frame-Options", "DENY"),       # no clickjacking
                                                     ("Cross-Origin-Resource-Policy", "same-origin")]), body)

    def host_names(self) -> set:
        names = {"127.0.0.1", "localhost", "::1"}
        if self.cfg["lan"]:
            names |= self.addrs | {str(h).lower() for h in self.cfg.get("extra_hosts", [])}
        return names

    def _host_ok(self, host_hdr: str) -> bool:
        try:
            u = urllib.parse.urlsplit("//" + (host_hdr or ""))
            return (u.hostname or "") in self.host_names() and (u.port is None or u.port == int(self.cfg["port"]))
        except ValueError:
            return False

    def _origin_ok(self, origin: str) -> bool:
        if not origin:
            return bool(self.cfg.get("allow_no_origin"))             # browsers always send Origin on WebSocket handshakes
        if origin == "null":
            return bool(self.cfg.get("allow_file_origin", True))     # tabula.html opened from disk (still needs the token)
        if origin in self.cfg["extra_origins"]:
            return True
        try:
            u = urllib.parse.urlsplit(origin)
            port = u.port or (443 if u.scheme == "https" else 80)
        except ValueError:
            return False
        return u.scheme in ("http", "https") and (u.hostname or "") in self.host_names() and port == int(self.cfg["port"])

    @staticmethod
    def _is_local(connection) -> bool:
        try:
            ip = str(connection.remote_address[0])
        except Exception:
            return False
        return ip in ("127.0.0.1", "::1") or ip.startswith("::ffff:127.")

    async def process_request(self, connection, request):
        return await asyncio.to_thread(self._process_request, connection, request)   # page assembly + file reads off the loop

    def _page_state(self) -> Optional[dict]:
        try:
            st = json.loads((self.store.home / "page-state.json").read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(st, dict):
            return None
        if isinstance(st.get("host"), dict):
            st["host"].pop("token", None)                     # a token must never be served, whoever saved it
        return st

    def _page(self) -> bytes:
        ps = self.store.home / "page-state.json"
        key = (self.page_path.stat().st_mtime_ns if self.page_path.exists() else 0, ps.stat().st_mtime_ns if ps.exists() else 0)
        if self._page_cache and self._page_cache[0] == key:
            return self._page_cache[1]
        html = self.page_path.read_text(encoding="utf-8")
        # the token is NOT inlined: any local process (or LAN device) can GET this page. It reaches the browser
        # only through the URL fragment the host opens / prints (#t=…), which is never sent over the network.
        boot = {"version": VERSION, "lan": bool(self.cfg["lan"]), "tokenLen": len(self.store.token)}
        if (self.store.home / "models" / "hand_landmarker.task").is_file():
            boot["handModel"] = "/models/hand_landmarker.task"
        st = self._page_state()
        if st is not None:
            boot["cfg"] = st
        js = json.dumps(boot, ensure_ascii=True)                   # ASCII: no lone surrogate can break the UTF-8 encode
        for a, b in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
            js = js.replace(a, b)                                     # nothing in saved state can close or comment out the script
        body = html.replace("<!--TABULA_BOOT-->", "<script>window.TABULA_BOOT=" + js + ";</script>", 1).encode("utf-8")
        self._page_cache = (key, body)
        return body

    def _process_request(self, connection, request):
        path = request.path
        u = urllib.parse.urlsplit(path)
        if not self._host_ok(request.headers.get("Host", "")):
            return self._resp(421, b"misdirected request (Host header rejected: DNS-rebinding guard)", "text/plain")
        if u.path == "/ws":
            tok = urllib.parse.parse_qs(u.query).get("token", [""])[0]
            if not hmac.compare_digest(tok, self.store.token):
                self.store.audit("reject", why="bad token", origin=request.headers.get("Origin"))
                return self._resp(403, b"bad token", "text/plain")
            origin = request.headers.get("Origin", "")
            if not self._origin_ok(origin):
                self.store.audit("reject", why="origin", origin=origin or "(none)")
                return self._resp(403, b"origin not allowed", "text/plain")
            return None
        if u.path in ("/", "/index.html"):
            try:
                return self._resp(200, self._page(), "text/html; charset=utf-8")
            except Exception:
                return self._resp(500, b"tabula.html not found next to tabula_host.py", "text/plain")
        if u.path == "/open":                                     # first load from the redirect file: nothing to serve
            return self._resp(404, b"not found", "text/plain")
        if u.path == "/tokens.svg":
            try:
                return self._resp(200, marker_sheet_svg().encode(), "image/svg+xml")
            except Exception as e:
                return self._resp(500, str(e).encode(), "text/plain")
        m = re.fullmatch(r"/models/([A-Za-z0-9_][A-Za-z0-9_.-]*)", u.path)
        if m:
            p = self.store.home / "models" / m.group(1)
            if p.is_file() and p.resolve().parent == (self.store.home / "models").resolve():
                return self._resp(200, p.read_bytes(), "application/octet-stream")
            return self._resp(404, b"no such model", "text/plain")
        if u.path == "/health":
            h = {"ok": True, "version": VERSION, "armed": self.armed, "backend": self.inp.name, "clients": len(self.clients), "sense": self.sense_status}
            if self._is_local(connection):
                h["windows"] = [{"role": c.role, "armed": c is self.arm_client, "idle_s": round(time.time() - c.last_seen, 1)} for c in list(self.clients)]
                if self.dry:
                    h["dry_events"] = [list(e) for e in list(self.inp.events)[-40:]]
            return self._resp(200, json.dumps(h, default=str).encode(), "application/json")
        return self._resp(404, b"not found", "text/plain")

    # ---------------- WebSocket side ----------------
    async def handler(self, ws):
        c = Client(ws)
        self.clients.add(c)
        self.store.audit("connect", addr=str(c.addr))
        workers = [asyncio.create_task(c.writer()), asyncio.create_task(self._worker(c, c.q_act)), asyncio.create_task(self._worker(c, c.q_ptr))]
        try:
            await c.send(await asyncio.to_thread(self.welcome))
            if self.focus:
                await c.send(dict(self.focus, t="focus"))
            if self.observe_ok():
                await c.send({"t": "clip", "history": list(self.clip_hist)})
            await c.send(self.obs.state())
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                if isinstance(m, dict):
                    c.last_seen = time.time()
                    await self.route(c, m)
        except Exception as e:
            log.debug("client closed: %s", e)
        finally:
            c.dead = True
            self.clients.discard(c)
            for t in workers + list(c.tasks):
                t.cancel()
            if c.portal:
                c.portal.cancel()
            if self.armed and (c is self.arm_client or not self.clients):
                self.disarm("the arming window disconnected")
            if c is self.arm_client:
                self.arm_client = None
            self.store.audit("disconnect", addr=str(c.addr))

    async def route(self, c, m):
        """The reader loop never waits on slow work, so PANIC / disarm are handled the moment they arrive:
        input goes to per-client ordered queues, slow requests run as tasks, control messages run inline."""
        t, op = m.get("t"), m.get("op")
        if t in ("ptr", "touch"):
            if not self.armed or c is not self.arm_client:
                return
            rel = _release_msg(m)
            if not rel and not self.buckets[t].take():
                return                                          # rate limited (releases never are)
            if not rel and c.q_ptr.qsize() > 256:
                return                                          # far behind: drop moves, keep ups
            m["_gen"] = self.gen                                # a PANIC + quick re-arm must not replay older input
            c.q_ptr.put_nowait(m)
            return
        if t == "act" or (t == "win" and op != "list") or (t == "clip" and op == "set"):
            if c.q_act.qsize() >= 32:
                return await self._ack(c, m, False, err="busy — too many queued actions")
            c.q_act.put_nowait(m)
            return
        if t in ("vlm", "scan", "sense", "win", "clip"):
            task = asyncio.create_task(self._safe_dispatch(c, m))
            c.tasks.add(task)
            task.add_done_callback(c.tasks.discard)
            return
        await self._safe_dispatch(c, m)                         # hello · ping · arm · panic · portal · gc · cfg: all quick

    async def _worker(self, c, q):
        while True:
            m = await q.get()
            await self._safe_dispatch(c, m)

    async def _ack(self, c, m, ok=True, **kw):
        try:
            await c.send({"t": "ack", "id": m.get("id"), "ok": ok, **kw})
        except Exception:
            pass

    async def _safe_dispatch(self, c, m):
        try:
            await self.dispatch(c, m)
        except asyncio.CancelledError:
            raise
        except Aborted as e:
            await self._ack(c, m, False, err="aborted: " + str(e))
        except Exception as e:
            log.exception("dispatch %s", m.get("t"))
            await self._ack(c, m, False, err=str(e))

    def broadcast_nowait(self, obj):
        for c in list(self.clients):
            c.send_nowait(obj)

    async def broadcast(self, obj):                          # enqueue only: never waits on any socket
        self.broadcast_nowait(obj)

    def post(self, obj):
        """thread-safe broadcast"""
        if self.loop:
            self.loop.call_soon_threadsafe(self.broadcast_nowait, obj)

    def disarm(self, reason):
        """loop thread only. Stops new input at once (the guarded backend refuses it), aborts in-flight typing at the
        next chunk, drops queued input, then releases every held key, button and touch."""
        was = self.armed
        self.armed = False
        self.gen += 1
        for c in list(self.clients):
            for q in (c.q_act, c.q_ptr):
                while not q.empty():
                    try:
                        m = q.get_nowait()
                    except Exception:
                        break
                    if m.get("id"):
                        c.send_nowait({"t": "ack", "id": m["id"], "ok": False, "err": "aborted: disarmed before it ran"})

        def release():
            try:
                self.inp.release_all()
            except Exception:
                pass
            self.buttons_since.clear()
        threading.Thread(target=release, daemon=True, name="tabula-release").start()
        if was:
            log.warning("DISARMED — %s", reason)
            self.store.audit("disarm", reason=reason)
        self.post({"t": "armed", "on": False, "reason": reason})

    def _gate_ok(self, gate) -> tuple:
        if self.cfg["bind"] not in ("127.0.0.1", "::1", "localhost") and not self.cfg["lan"]:
            return False, "host bound to a non-loopback address without LAN mode"
        if self.shell_wildcard():
            return False, "allow-list contains a shell -c / wildcard entry"
        if not isinstance(gate, dict) or not isinstance(gate.get("verdicts"), list) or not gate["verdicts"]:
            return False, "no TRIBUNAL report"
        if abs(time.time() * 1000 - float(gate.get("at", 0))) > 120_000:
            return False, "TRIBUNAL report is stale — re-run the critics"
        bad = [v.get("id") for v in gate["verdicts"] if v.get("v") == "FAIL" or (v.get("v") == "WARN" and gate.get("strict", True) and not v.get("acked"))]
        if bad:
            return False, "TRIBUNAL not unanimous: " + ", ".join(map(str, bad))
        return True, ""

    async def dispatch(self, c, m):
        t, mid = m.get("t"), m.get("id")

        async def ack(ok=True, **kw):
            await c.send({"t": "ack", "id": mid, "ok": ok, **kw})

        if t == "hello":
            c.role = str(m.get("role", "?"))[:16]
            if isinstance(m.get("desk"), dict):
                self.desk = (float(m["desk"].get("w", 1000)), float(m["desk"].get("h", 562.5)))
            return await ack()
        if t == "ping":
            return await c.send({"t": "pong", "ts": m.get("ts"), "hts": time.time() * 1000})
        if t == "arm":
            if not m.get("on"):
                self.disarm("operator")
                return await ack()
            if self.armed and self.arm_client is not None and self.arm_client is not c and not self.arm_client.dead:
                self.store.audit("arm-refused", why="armed by another window", addr=str(c.addr))
                return await ack(False, err="already armed by another window — disarm or PANIC there first")
            ok, why = self._gate_ok(m.get("gate"))
            if not ok:
                self.store.audit("arm-refused", why=why)
                return await ack(False, err=why)
            self.armed, self.last_activity, self.arm_client = True, time.time(), c    # input is accepted from this window only
            self.store.audit("arm", gate=m.get("gate"), dry=self.dry, addr=str(c.addr))
            log.warning("ARMED by the page (TRIBUNAL unanimous)%s", " — dry-run, nothing is injected" if self.dry else "")
            await self.broadcast({"t": "armed", "on": True})
            return await ack()
        if t == "panic":
            self.disarm("PANIC: " + str(m.get("reason", "")))
            return
        if t == "act":
            if not self.armed:
                return await ack(False, err="not armed")
            if c is not self.arm_client:
                return await ack(False, err="input is bound to the window that armed — arm from this window")
            a = m.get("a") if isinstance(m.get("a"), dict) else {}
            if not self.buckets["midi" if a.get("do") == "midi" else "act"].take():
                return await ack(False, err="rate limited")
            self.last_activity = time.time()
            self.store.audit("act", a={k: (redact(v) if k in ("s", "text") else v) for k, v in a.items()}, dry=self.dry)
            try:
                out = await self.act(a, self.gen)
                return await ack(True, out=out, dry=self.dry)
            except Exception as e:
                return await ack(False, err=("aborted: " if isinstance(e, Aborted) else "") + str(e))
        if t == "ptr":
            if not self.armed or c is not self.arm_client or m.get("_gen", self.gen) != self.gen:
                return
            self.last_activity = time.time()
            try:
                await asyncio.to_thread(self.ptr, m, m.get("_gen", self.gen))
            except Exception as e:                                     # a failed pointer op must never end the worker
                log.debug("ptr %s: %s", m.get("op"), e)
            return
        if t == "touch":
            if not self.armed or c is not self.arm_client or m.get("_gen", self.gen) != self.gen:
                return
            self.last_activity = self.last_touch = time.time()
            try:
                await asyncio.to_thread(self.touch, m.get("contacts") or [], m.get("_gen", self.gen))
            except Exception as e:
                log.debug("touch: %s", e)
            return
        if t == "portal":
            if c.portal:
                c.portal.cancel()
                c.portal = None
            if m.get("op") == "start":
                if not self.observe_ok():
                    return await c.send({"t": "portal", "op": "refused", "err": "PORTAL needs the host armed (observe_disarmed is off)"})
                c.portal = asyncio.ensure_future(self.portal_loop(c, m))
            return
        if t == "win":
            op = m.get("op")
            if op == "list":
                wins = await asyncio.to_thread(self.plat.windows)
                return await c.send({"t": "windows", "list": wins, "id": mid})
            if not self.armed:
                return await ack(False, err="not armed")
            if c is not self.arm_client:
                return await ack(False, err="input is bound to the window that armed")
            if op not in ("focus", "min", "max", "restore", "close", "move"):
                return await ack(False, err="unknown window op")
            if not self.buckets["win"].take():
                return await ack(False, err="rate limited")
            self.last_activity = time.time()
            self.store.audit("win", op=op, wid=m.get("id"))
            if self.dry:
                self.inp._rec("win", op, m.get("id"), m.get("rect"))
                return await ack(True, dry=True)
            ok = await asyncio.to_thread(self.plat.win_op, op, m.get("id"), m.get("rect"))
            await ack(ok)
            await c.send({"t": "windows", "list": await asyncio.to_thread(self.plat.windows)})
            return
        if t == "clip":
            op = m.get("op")
            if op == "set":                                              # changes the computer → armed, arming window only
                if not self.armed or c is not self.arm_client:
                    return await ack(False, err="not armed")
                txt = str(m.get("text", ""))
                if len(txt) > self.cfg["limits"]["paste"]:
                    return await ack(False, err="text too long")
                self.store.audit("clip-set", text=redact(txt), dry=self.dry)
                if self.dry:
                    self.inp._rec("clip-set", redact(txt))
                    return await ack(True, dry=True)
                return await ack(await asyncio.to_thread(self.plat.clip_set, txt))
            if not self.observe_ok():
                return await ack(False, err="clipboard history needs the host armed (observe_disarmed is off)")
            if op == "history":
                return await c.send({"t": "clip", "history": list(self.clip_hist), "id": mid})
            return await ack(False, err="unknown clip op")
        if t == "vlm":
            if not self.buckets["vlm"].take():
                return await c.send({"t": "vlm", "id": mid, "ok": False, "err": "rate limited"})
            img = str(m.get("img", ""))
            b64 = img.split(",", 1)[1] if img.startswith("data:") else img
            if len(b64) > 12_000_000:
                return await c.send({"t": "vlm", "id": mid, "ok": False, "err": "image too large"})
            try:
                text, prov = await asyncio.to_thread(self.vlm.ask, b64, m.get("mode", "explain"), m.get("prompt", ""))
                return await c.send({"t": "vlm", "id": mid, "ok": True, "text": text, "provider": prov})
            except Exception as e:
                return await c.send({"t": "vlm", "id": mid, "ok": False, "err": str(e)})
        if t == "sense":
            return await self.sense_cmd(c, m, ack)
        if t == "gc":
            if m.get("op") == "shown" and self.gc_wait and self.gc_wait[0] == m.get("k"):
                self.gc_wait[1].set()
            return
        if t == "scan":
            return await self.scan(c, m)
        if t == "cfg":
            if m.get("op") == "save" and isinstance(m.get("cfg"), dict):
                if not self.buckets["cfg"].take():
                    return await ack(False, err="rate limited")
                st = m["cfg"]
                if isinstance(st.get("host"), dict):
                    st["host"].pop("token", None)                         # never persisted, never served
                data = json.dumps(st, ensure_ascii=True, allow_nan=False, default=str)
                if len(data) > 2_000_000:
                    return await ack(False, err="page state larger than 2 MB")
                await asyncio.to_thread(write_private, self.store.home / "page-state.json", data)
                return await ack()
            return await ack(False, err="unknown cfg op")
        return await ack(False, err=f"unknown message type {t!r}")

    # ---------------- actions ----------------
    def _alive(self, gen):
        if not self.armed or self.gen != gen:
            raise Aborted("disarmed")

    async def act(self, a: dict, gen: int = 0):
        d, L = a.get("do"), self.cfg["limits"]
        if d == "key":
            seq = resolve_chord(a.get("c"))
            if not seq:
                raise ValueError("shortcut not available on " + OS)
            if len(seq) > L["chords"]:
                raise ValueError(f"a key sequence may hold at most {L['chords']} chords")

            def run():
                for mods, key in seq:
                    self._alive(gen)                                     # PANIC between chords stops the rest
                    self.inp.chord(mods, key)
                    time.sleep(0.03)
            return await asyncio.to_thread(run)
        if d == "text":
            s = str(a.get("s", ""))
            if len(s) > L["text"]:
                raise ValueError(f"text longer than {L['text']} characters — use paste")
            return await asyncio.to_thread(self.type_text, s, gen)
        if d == "paste":
            txt = str(a.get("text", ""))
            if len(txt) > L["paste"]:
                raise ValueError(f"paste longer than {L['paste']} characters")
            return await asyncio.to_thread(self.paste_text, txt, gen, False)
        if d == "wheel":
            return await asyncio.to_thread(self.ptr, {"op": "wheel", "dy": a.get("dy", 0), "dx": a.get("dx", 0), "mods": a.get("mods", "")})
        if d == "media":
            op = a.get("op")
            if op not in MEDIA_KEYS:
                raise ValueError("unknown media op")
            return await asyncio.to_thread(self.inp.media, op)
        if d == "launch":
            entry = self.cfg["launch"].get(str(a.get("id")))
            if not entry:
                raise ValueError(f"'{a.get('id')}' is not in the launch allow-list (~/.tabula/config.json)")
            why = allowlist_problem(entry.get("argv") if isinstance(entry, dict) else entry)
            if why:
                raise ValueError("refused: " + why)
            if self.dry:
                self.inp._rec("launch", entry)
                return "dry-run"
            argv, cwd = self.resolve_argv(entry)
            kw = {"creationflags": 0x00000010} if OS == "win" else {"start_new_session": True}   # CREATE_NEW_CONSOLE
            subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
            return "launched " + Path(argv[0]).name
        if d == "run":
            spec = self.cfg["run"].get(str(a.get("id")))
            if not spec:
                raise ValueError(f"'{a.get('id')}' is not in the run allow-list")
            why = allowlist_problem(spec.get("argv", []))
            if why:
                raise ValueError("refused: " + why)
            if self.dry:
                self.inp._rec("run", spec["argv"])
                return "dry-run: " + " ".join(spec["argv"])

            def run():
                try:
                    argv, cwd = self.resolve_argv({"argv": spec["argv"], "cwd": spec.get("cwd", "~")})
                    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=min(60, float(spec.get("timeout", 10))))
                    return (r.stdout + r.stderr)[-4000:]
                except FileNotFoundError as e:
                    return str(e)
                except subprocess.TimeoutExpired:
                    return f"{spec['argv'][0]}: timed out"
            return await asyncio.to_thread(run)
        if d == "url":
            href = str(a.get("href", ""))
            if urllib.parse.urlsplit(href).scheme not in self.cfg["url_schemes"]:
                raise ValueError("URL scheme not allowed")
            if not self.dry:
                webbrowser.open(href)
            return "opened"
        if d == "obs":
            if self.dry:                                                  # dry-run changes nothing anywhere, OBS included
                self.inp._rec("obs", a.get("req"))
                return "dry-run"
            await self.obs.act(a.get("req"), a.get("data"))
            return "ok"
        if d == "osc":
            tgt = self.cfg["osc_targets"].get(str(a.get("target")))
            if not tgt:
                raise ValueError("unknown OSC target")
            if self.dry:
                self.inp._rec("osc", tgt, a.get("addr"))
                return "dry-run"
            self.osc.send(tgt[0], tgt[1], osc_message(str(a.get("addr", "/tabula")), *a.get("args", [])))
            return "sent"
        if d == "midi":
            if self.dry:
                self.inp._rec("midi", a.get("msg"))
                return "dry-run"
            if self.midi is None:
                self.midi = MidiOut(self.cfg["midi_port"])
            self.midi.send(a.get("msg", []))
            return "sent"
        if d == "http":
            spec = self.cfg["http"].get(str(a.get("id")))
            if not spec:
                raise ValueError("unknown HTTP action")
            if self.dry:
                self.inp._rec("http", spec.get("url"))
                return "dry-run"

            def run():
                body = json.dumps(spec["json"]).encode() if "json" in spec else None
                req = urllib.request.Request(spec["url"], data=body, method=spec.get("method", "POST"), headers={"content-type": "application/json", **spec.get("headers", {})})
                with urllib.request.urlopen(req, timeout=8) as r:
                    return f"HTTP {r.status}"
            return await asyncio.to_thread(run)
        if d == "click":
            return await asyncio.to_thread(self.inp.click, "left")
        raise ValueError(f"unknown action {d!r}")

    TEXT_CHUNK = 12                                                   # PANIC stops typing within one chunk

    def type_text(self, s, gen=None):
        gen = self.gen if gen is None else gen
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        via = self.cfg.get("type_via", "auto")
        if via == "paste" or (via == "auto" and not self.inp.can_type(s)):
            return self.paste_text(s, gen, True)                         # validated up front: nothing typed twice
        i = 0
        try:
            while i < len(s):
                self._alive(gen)
                self.inp.text(s[i:i + self.TEXT_CHUNK])
                i += self.TEXT_CHUNK
        except NotImplementedError:                                       # backend refused mid-way: paste only the rest
            self.paste_text(s[i:], gen, True)

    def paste_text(self, s, gen, restore):
        """clipboard + mod+V; restores the previous clipboard when used on behalf of 'type'. Dry-run touches nothing."""
        self._alive(gen)
        mod = frozenset({"cmd" if OS == "mac" else "ctrl"})
        if self.dry:
            self.inp._rec("paste", redact(s))
            self.inp.chord(mod, "v")
            return "dry-run"
        old = self.plat.clip_get() if restore else None
        if not self.plat.clip_set(s):
            raise RuntimeError("clipboard unavailable")
        time.sleep(0.05)
        self._alive(gen)
        self.inp.chord(mod, "v")
        if restore and old is not None:
            time.sleep(0.15)
            self.plat.clip_set(old)

    MODS = {"ctrl", "shift", "alt", "win", "cmd"}

    def _xy(self, m):
        x, y = float(m["x"]), float(m["y"])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("non-finite coordinate")
        bx, by, bw, bh = self.plat.desktop_box()
        return int(min(max(x, bx), bx + bw - 1)), int(min(max(y, by), by + bh - 1))

    def ptr(self, m, gen=None):
        gen = self.gen if gen is None else gen
        op = m.get("op")
        W = int(self.cfg["limits"]["wheel"])
        btn = m.get("btn", "left") if m.get("btn") in ("left", "right", "middle") else "left"
        if op == "up":                                                    # a release happens even if the move fails
            try:
                if m.get("x") is not None:
                    self.inp.move(*self._xy(m))
            finally:
                self.inp.button(btn, False)
                self.buttons_since.pop(btn, None)
            return
        self._alive(gen)
        if m.get("x") is not None and op in ("move", "down", "click"):
            self.inp.move(*self._xy(m))
        if op in ("move", "rel"):
            for b in self.buttons_since:                                  # a drag in progress is not a stuck button
                self.buttons_since[b] = time.time()
        if op == "rel":
            self.inp.move_rel(max(-4000, min(4000, int(m.get("dx", 0)))), max(-4000, min(4000, int(m.get("dy", 0)))))
        elif op == "down":
            self.inp.button(btn, True)
            self.buttons_since[btn] = time.time()
        elif op == "click":
            self.inp.click(btn)
        elif op == "wheel":
            mods = [norm_mod(x) for x in str(m.get("mods", "")).split("+") if x]
            if any(x not in self.MODS for x in mods):
                raise ValueError("wheel modifiers must be ctrl/shift/alt/win/cmd")
            dy, dx = max(-W, min(W, int(m.get("dy", 0)))), max(-W, min(W, int(m.get("dx", 0))))
            pressed = []
            try:
                for x in mods:
                    self.inp.key(x, True)
                    pressed.append(x)
                for axis, n in (("dy", dy), ("dx", dx)):                  # one notch at a time: PANIC stops the rest
                    for _ in range(abs(n)):
                        self._alive(gen)
                        self.inp.wheel(*((1 if n > 0 else -1, 0) if axis == "dy" else (0, 1 if n > 0 else -1)))
            finally:
                for x in reversed(pressed):
                    self.inp.key(x, False)

    def touch(self, contacts, gen=None):
        out = []
        for c in list(contacts)[:10]:
            if not isinstance(c, dict) or c.get("phase") not in ("down", "move", "up"):
                continue
            try:
                x, y = self._xy(c)
            except (KeyError, TypeError, ValueError):
                continue
            out.append({"id": str(c.get("id"))[:32], "x": x, "y": y, "phase": c["phase"]})
        contacts = out
        if not contacts:
            return
        if not all(c["phase"] == "up" for c in contacts):
            self._alive(self.gen if gen is None else gen)
        try:
            self.inp.touch_frame(contacts)
        except NotImplementedError:                                   # degrade: first contact drives the mouse
            if not contacts:
                return
            c0 = contacts[0]
            self.inp.move(int(c0["x"]), int(c0["y"]))
            if c0["phase"] == "down":
                self.inp.button("left", True)
            elif c0["phase"] == "up":
                self.inp.button("left", False)

    # ---------------- PORTAL streaming ----------------
    def portal_region(self, target: dict):
        screens = self.plat.screens()
        prim = next((s for s in screens if s["primary"]), screens[0])
        if target.get("win") is not None:
            r = self.plat.window_rect(target["win"])
            if r and r[2] > 20 and r[3] > 20:
                return r, next((w["title"] for w in self.plat.windows() if str(w["id"]) == str(target["win"])), "window")
        if target.get("screen") is not None:
            s = next((s for s in screens if s["id"] == target["screen"]), prim)
            return [s["x"], s["y"], s["w"], s["h"]], s["name"]
        if target.get("magnify"):
            z = max(1.5, float(target["magnify"]))
            cx, cy = (self.inp.cursor() or [prim["x"] + prim["w"] / 2, prim["y"] + prim["h"] / 2])
            s = next((s for s in screens if s["x"] <= cx < s["x"] + s["w"] and s["y"] <= cy < s["y"] + s["h"]), prim)
            w, h = s["w"] / z, s["h"] / z
            x = min(max(s["x"], cx - w / 2), s["x"] + s["w"] - w)
            y = min(max(s["y"], cy - h / 2), s["y"] + s["h"] - h)
            return [int(x), int(y), int(w), int(h)], f"magnifier ×{z:g}"
        f = self.focus
        if f and f.get("rect") and f["rect"][2] > 50 and f["rect"][3] > 50:
            return f["rect"], f.get("title") or f.get("app")
        return [prim["x"], prim["y"], prim["w"], prim["h"]], prim["name"]

    async def portal_loop(self, c: Client, m: dict):
        fps = min(30.0, max(1.0, float(m.get("fps", 15))))
        maxw = int(min(1920, max(320, int(m.get("maxW", 1280)))))
        q = int(min(90, max(30, int(m.get("q", 70)))))
        target = m.get("target") or {"follow": True}
        seq, t_sim = 0, 0.0
        def capture(t_sim):
            rect, title = self.portal_region(target)
            img, cursor = self.plat.grab(rect), self.inp.cursor()
            sim = img is None
            if sim:
                img = synthetic_screen(1280, 720, t_sim, "TABULA-Ω · no capturable display (synthetic)", None)
            img = resize_max(img, maxw)
            return rect, title, cursor, sim, int(img.shape[1]), int(img.shape[0]), encode_jpeg(img, q)
        try:
            while self.observe_ok() and not c.dead:
                t0 = time.perf_counter()
                if c.frames < 2:                                          # the window keeps up: capture the next frame
                    t_sim += 1 / fps
                    rect, title, cursor, sim, w, h, jpg = await asyncio.to_thread(capture, t_sim)
                    if jpg:
                        hdr = json.dumps({"seq": seq, "rect": rect, "w": w, "h": h, "cursor": cursor, "title": title, "mime": "image/jpeg", "sim": sim}).encode()
                        if c.send_nowait(struct.pack("<I", len(hdr)) + hdr + jpg, frame=True):
                            seq += 1
                await asyncio.sleep(max(0.0, 1 / fps - (time.perf_counter() - t0)))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("portal stopped: %s", e)

    # ---------------- sensing ----------------
    async def sense_cmd(self, c, m, ack):
        op = m.get("op")
        if isinstance(m.get("desk"), dict):
            self.desk = (float(m["desk"].get("w", 1000)), float(m["desk"].get("h", 562.5)))
        if op == "start":
            try:
                await asyncio.to_thread(self.start_sense, str(m.get("source", "synthetic")), int(m.get("tangibles", -1)))
                return await ack(True, msg=f"sensing: {self.sense_status.get('source')}")
            except Exception as e:
                return await ack(False, err=str(e))
        if op == "stop":
            await asyncio.to_thread(self.stop_sense)
            return await ack(True, msg="sensing stopped")
        if op == "background":
            if self.engine:
                self.engine.relearn()
                return await ack(True, msg="keep the desk clear for a second — learning background")
            return await ack(False, err="no depth source running")
        if op == "tapcal":
            if not self.sense_thread:
                return await ack(False, err="start a sensor first")
            self.tapcal = TapCal()
            fx, fy = TapCal.TARGETS[0]
            await self.broadcast({"t": "tapcal", "op": "target", "i": 0, "n": len(TapCal.TARGETS), "x": fx, "y": fy})
            return await ack(True, msg="touch each ring and hold still")
        if op == "graycode":
            asyncio.ensure_future(self.graycode(c, int(m.get("cam", 0)), int(m.get("texW", 1920)), int(m.get("texH", 1080)), int(m.get("step", 16)), float(m.get("settle", 0.2))))
            return await ack(True, msg="Gray-code capture started")
        if op == "status":
            return await ack(True, status=self.sense_status)
        return await ack(False, err="unknown sense op")

    def start_sense(self, source: str, tangibles_cam: int = -1):
        with self.sense_lock:
            self._start_sense(source, tangibles_cam)

    def _start_sense(self, source: str, tangibles_cam: int = -1):
        self._stop_sense()
        self.sense_stop = threading.Event()
        if tangibles_cam is not None and tangibles_cam >= 0:
            self.tangibles = Tangibles(tangibles_cam, self.cfg["tokens_corner_ids"])
            if self.cfg["calib"].get("H_desk_cam"):
                self.tangibles.H = self.cfg["calib"]["H_desk_cam"]
        if source.startswith("lightplane"):
            idx = int(source.split(":", 1)[1]) if ":" in source else 0
            self.lightplane = LightPlane(idx, self.cfg["sense"]["lightplane_thresh"])
            self.engine = None
            target = self._lightplane_loop
        elif source == "tuio":
            self.tuio_in = TUIOIn(int(self.args.tuio_in or 3333))
            target = self._tuio_loop
        elif source == "none":
            target = self._tangibles_only_loop
        else:
            src = make_depth(source)
            src.open()
            sensor_h = 800.0
            self.engine = TouchEngine(self.cfg["sense"], self.desk, sensor_h)
            if self.cfg["calib"].get("H_desk_raw") and self.cfg["calib"].get("raw_source") == source:
                self.engine.H = self.cfg["calib"]["H_desk_raw"]
            elif getattr(src, "desk_aligned", False):
                self.engine.H = None
            self._src = src
            target = self._depth_loop
        self.sense_status = {"source": source, "running": True, "calibrated": bool(self.cfg["calib"].get("H_desk_raw")) or source == "synthetic", "tangibles": tangibles_cam}
        self.sense_thread = threading.Thread(target=target, daemon=True, name="tabula-sense")
        self.sense_thread.start()
        self.store.audit("sense-start", source=source)
        log.info("sensing started: %s", source)

    def stop_sense(self):
        with self.sense_lock:
            self._stop_sense()

    def _stop_sense(self):
        if self.sense_thread:
            self.sense_stop.set()
            for obj in (self.tuio_in,):                                  # unblock a recvfrom() so the thread can exit
                try:
                    if obj:
                        obj.close()
                except Exception:
                    pass
            self.sense_thread.join(timeout=2)
        for obj in (getattr(self, "_src", None), self.lightplane, self.tangibles, self.tuio_in):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self._src = self.lightplane = self.tangibles = self.tuio_in = None
        self.sense_thread, self.engine, self.tapcal = None, None, None
        self.sense_status = {"source": None}

    def _emit_touches(self, src, contacts, hands=(), heads=(), objects=(), palm=False):
        msg = {"t": "touches", "src": src, "contacts": contacts, "hands": list(hands), "heads": list(heads), "objects": list(objects), "palm": palm, "ts": time.time()}
        self.post(msg)
        if palm and self.armed:
            self.loop.call_soon_threadsafe(self.disarm, "flat palm on the desk")
        tuio = self.cfg.get("tuio_out")
        if tuio:
            self.fseq += 1
            try:
                self.osc.send(tuio[0], tuio[1], tuio_frame([dict(c, id=int(c["id"])) for c in contacts if c["phase"] in ("down", "move")], self.fseq))
            except Exception:
                pass

    def _tokens(self):
        if not self.tangibles:
            return []
        r = self.tangibles.read()
        if r and r["calibrated"] and not self.cfg["calib"].get("H_desk_cam"):
            self.cfg["calib"]["H_desk_cam"] = self.tangibles.H
        return r["tokens"] if r else []

    def _tapcal_feed(self, raw_pts):
        tc = self.tapcal
        if not tc:
            return
        if tc.feed(raw_pts, time.time()) == "next":
            if tc.done:
                H, rms, n = tc.solve()
                self.tapcal = None
                if H is None:
                    self.post({"t": "tapcal", "op": "done", "ok": False, "err": "solve failed"})
                    return
                self.cfg["calib"]["H_desk_raw"], self.cfg["calib"]["raw_source"] = H, self.sense_status.get("source")
                self.store.save()
                if self.engine:
                    self.engine.H = H
                self.sense_status["calibrated"] = True
                self.post({"t": "tapcal", "op": "done", "ok": True, "rmsMm": rms * self.desk[0], "n": n})
                self.store.audit("tapcal", rms=rms, n=n)
            else:
                fx, fy = TapCal.TARGETS[tc.i]
                self.post({"t": "tapcal", "op": "target", "i": tc.i, "n": len(TapCal.TARGETS), "x": fx, "y": fy})

    def _depth_loop(self):
        src, eng = self._src, self.engine
        while not self.sense_stop.is_set():
            try:
                depth, ts = src.read()
            except Exception as e:
                log.warning("depth read failed: %s", e)
                time.sleep(0.5)
                continue
            try:
                self._depth_step(src, eng, depth, ts)
            except Exception as e:                                        # one bad frame must not end sensing
                log.warning("depth frame failed: %s", e)
                time.sleep(0.05)

    def _depth_step(self, src, eng, depth, ts):
        r = eng.step(depth, ts)
        if isinstance(src, SyntheticDepth):
            time.sleep(1 / src.hz)
        if r is None:
            self.sense_status["learning"] = True
            return
        self.sense_status.update(learning=False, **eng.stats)
        if self.tapcal:
            self._tapcal_feed([tr.raw for tr in eng.tracks.values() if tr.down])
        toks = self._tokens()
        self._emit_touches("d", r["contacts"], r["hands"], r["heads"], r["objects"] + toks, r["palm"])

    def _lightplane_loop(self):
        """IR light-plane blobs → contacts with down/up hysteresis (a blob must persist `down_frames` to press and be
        missing `up_frames` to lift), so sensor flicker neither taps nor drops a drag."""
        lp, tracks, nid = self.lightplane, {}, 1
        dn, upf = max(1, int(self.cfg["sense"].get("down_frames", 2))), max(1, int(self.cfg["sense"].get("up_frames", 2)))
        while not self.sense_stop.is_set():
            try:
                pts, shape = lp.read()
            except Exception as e:
                log.warning("light-plane read failed: %s", e)
                time.sleep(0.5)
                continue
            if pts is None:
                time.sleep(0.05)
                continue
            try:
                if self.tapcal:
                    self._tapcal_feed(pts)
                raw = str(self.cfg["calib"].get("raw_source") or "")
                H = self.cfg["calib"].get("H_desk_raw") if raw.startswith("lightplane") else None
                desk = [h_apply(H, *p) if H else (p[0] / shape[1], p[1] / shape[0]) for p in pts]
                out, used = [], set()
                for u, v in desk:
                    cand = [(math.dist(t["p"], (u, v)), tid) for tid, t in tracks.items() if tid not in used]
                    d, tid = min(cand, default=(1e9, None))
                    if tid is None or d > 0.05:
                        tid, nid = nid, nid + 1
                        tracks[tid] = {"p": (u, v), "hits": 0, "miss": 0, "live": False}
                    t = tracks[tid]
                    used.add(tid)
                    t["p"], t["hits"], t["miss"] = (u, v), t["hits"] + 1, 0
                    if t["live"]:
                        out.append({"id": tid, "x": u, "y": v, "phase": "move"})
                    elif t["hits"] >= dn:
                        t["live"] = True
                        out.append({"id": tid, "x": u, "y": v, "phase": "down"})
                for tid in [k for k in tracks if k not in used]:
                    t = tracks[tid]
                    t["miss"] += 1
                    if not t["live"]:
                        del tracks[tid]                                   # a one-frame blob was noise
                    elif t["miss"] >= upf:
                        out.append({"id": tid, "x": t["p"][0], "y": t["p"][1], "phase": "up"})
                        del tracks[tid]
                    else:
                        out.append({"id": tid, "x": t["p"][0], "y": t["p"][1], "phase": "move"})   # hold through a dropout
                self._emit_touches("l", out, objects=self._tokens())
            except Exception as e:
                log.warning("light-plane frame failed: %s", e)

    def _tuio_loop(self):
        prev = set()
        while not self.sense_stop.is_set():
            tin = self.tuio_in
            if tin is None:
                return
            try:
                if tin.poll() is None:
                    continue
            except Exception as e:
                log.debug("tuio: %s", e)
                continue
            cur = dict(tin.cur)
            out = [{"id": k, "x": v[0], "y": v[1], "phase": "move" if k in prev else "down"} for k, v in cur.items()]
            out += [{"id": k, "x": 0, "y": 0, "phase": "up"} for k in prev - set(cur)]
            prev = set(cur)
            objs = [{"kind": "token", "id": o[0], "x": o[1], "y": o[2], "angle": math.degrees(o[3]), "w": 0.03, "h": 0.05} for o in list(tin.obj.values())]
            self._emit_touches("t", out, objects=objs)

    def _tangibles_only_loop(self):
        while not self.sense_stop.is_set():
            try:
                self._emit_touches("k", [], objects=self._tokens())
            except Exception as e:
                log.warning("tangibles frame failed: %s", e)
                time.sleep(0.5)
            time.sleep(1 / 20)

    async def graycode(self, c, cam, texW, texH, step, settle):
        """Closed-loop Gray-code for a host camera (tangibles / scan): the page projects, the host captures."""
        if cv2 is None or np is None:
            return await c.send({"t": "gc", "op": "done", "ok": False, "err": "needs numpy + opencv"})
        own, tang = False, self.tangibles
        cap = None
        if tang is None:
            cap, own = cv2.VideoCapture(cam), True

        def read():                                                   # through the tangibles lock when the sensing thread shares the camera
            if tang is not None:
                fr = tang.grab()
                return fr is not None, fr
            return cap.read()
        plan = gray_plan(texW, texH, step)
        frames = []
        try:
            for k in range(len(plan["pats"])):
                ev = asyncio.Event()
                self.gc_wait = (k, ev)
                await c.send({"t": "gc", "op": "show", "k": k, "step": step, "n": len(plan["pats"])})
                await asyncio.wait_for(ev.wait(), 6)
                await asyncio.sleep(settle)

                def grab():
                    acc = None
                    for i in range(3):
                        ok, fr = read()
                        if not ok:
                            raise RuntimeError("camera read failed")
                        if i == 0:
                            continue
                        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
                        acc = g if acc is None else (acc + g) / 2
                    return acc
                frames.append(await asyncio.to_thread(grab))
            col, row, valid = gray_decode(plan, frames)
            cam_pts, surf = gray_correspondences(plan, col, row, valid)
            H, idx, rms = homography_ransac(cam_pts, [(x / texW, y / texH) for x, y in surf], thresh=step / texW)
            if H is None:
                raise RuntimeError(f"only {len(cam_pts)} decodable cells")
            self.cfg["calib"]["H_desk_cam"] = H
            self.store.save()
            if self.tangibles:
                self.tangibles.H = H
            await c.send({"t": "gc", "op": "done", "ok": True, "cells": len(cam_pts), "inliers": len(idx), "rmsMm": rms * self.desk[0]})
        except Exception as e:
            try:
                await c.send({"t": "gc", "op": "done", "ok": False, "err": str(e)})
            except Exception:
                pass
        finally:
            self.gc_wait = None
            if own and cap is not None:
                cap.release()
            try:
                await c.send({"t": "gc", "op": "clear"})
            except Exception:
                pass

    async def scan(self, c, m):
        nack = lambda err: c.send({"t": "ack", "id": m.get("id"), "ok": False, "err": err})
        if not self.observe_ok():
            return await nack("scan needs the host armed (observe_disarmed is off)")
        if not self.buckets["scan"].take():
            return await nack("rate limited")
        H = self.cfg["calib"].get("H_desk_cam")
        frame = self.tangibles.last if self.tangibles else None
        if H is None or frame is None:
            return await nack("no calibrated host camera")
        x, y, w, h = [min(1.0, max(0.0, float(v))) for v in (list(m.get("rect") or [0, 0, 1, 1]) + [1, 1, 1, 1])[:4]]
        w, h = min(w, 1.0 - x), min(h, 1.0 - y)
        if w < 0.005 or h < 0.005:
            return await nack("scan rectangle too small")
        ppm = min(12.0, max(1.0, float(m.get("pxPerMm", 4))))
        ow, oh = w * self.desk[0] * ppm, h * self.desk[1] * ppm
        k = min(1.0, 4000.0 / max(ow, oh))                              # never more than 4000 px a side
        ow, oh = max(8, int(ow * k)), max(8, int(oh * k))

        def work():
            Hi = np.linalg.inv(np.asarray(H, float))
            corners = [h_apply(Hi.tolist(), px, py) for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
            M = cv2.getPerspectiveTransform(np.float32(corners), np.float32([(0, 0), (ow, 0), (ow, oh), (0, oh)]))
            return encode_jpeg(cv2.warpPerspective(frame.copy(), M, (ow, oh)), 88)
        jpg = await asyncio.to_thread(work)
        await c.send({"t": "ack", "id": m.get("id"), "ok": True, "img": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()})

    # ---------------- background loops ----------------
    def _obs_state(self, st):
        self.post(st)

    async def focus_loop(self):
        last = None
        while True:
            try:
                f = await asyncio.to_thread(self.plat.focus)
                if f:
                    key = (f.get("exe"), f.get("title"))
                    if key != last:
                        last = key
                        self.focus = f
                        await self.broadcast(dict(f, t="focus"))
            except Exception as e:
                log.debug("focus loop: %s", e)
            await asyncio.sleep(0.25)

    async def clip_loop(self):
        while True:
            try:
                if self.cfg.get("clip_watch", True) and self.observe_ok() and not await asyncio.to_thread(self.plat.clip_concealed):
                    txt = await asyncio.to_thread(self.plat.clip_get)
                    if txt and txt != self.last_clip and len(txt) < 20000:
                        self.last_clip = txt
                        self.clip_hist = collections.deque([h for h in self.clip_hist if h["text"] != txt], maxlen=40)
                        self.clip_hist.appendleft({"text": txt, "t": time.time() * 1000, "secret": looks_secret(txt)})   # the desk masks secrets
                        await self.broadcast({"t": "clip", "history": list(self.clip_hist)})
            except Exception as e:
                log.debug("clip loop: %s", e)
            await asyncio.sleep(1.0)

    async def telemetry_loop(self):
        while True:
            try:
                await self.broadcast(await asyncio.to_thread(self.telemetry.sample))
            except Exception as e:
                log.debug("telemetry loop: %s", e)
            await asyncio.sleep(1.0)

    async def safety_loop(self):
        """idle auto-disarm + stuck-button and stuck-touch watchdogs; an error in one pass never ends the loop"""
        while True:
            try:
                now = time.time()
                if self.armed and now - self.last_activity > self.cfg["idle_disarm_s"]:
                    self.disarm(f"idle for {self.cfg['idle_disarm_s']} s")
                ac = self.arm_client
                if self.armed and ac is not None and (ac.dead or now - ac.last_seen > float(self.cfg.get("deadman_s", 10))):
                    self.disarm(f"the arming window stopped answering for {self.cfg.get('deadman_s', 10)} s")
                for b, t0 in list(self.buttons_since.items()):
                    if now - t0 > self.cfg["hold_timeout_s"]:
                        log.warning("released %s button held for %.0f s (watchdog)", b, now - t0)
                        self.buttons_since.pop(b, None)
                        await asyncio.to_thread(self.inp.button, b, False)
                touches = dict(self.inp.touches or {})
                if touches and now - self.last_touch > float(self.cfg.get("touch_timeout_s", 3)):
                    log.warning("lifted %d touch contact(s) the page stopped updating (watchdog)", len(touches))
                    await asyncio.to_thread(self.inp.touch_frame, [{"id": k, "x": v[0], "y": v[1], "phase": "up"} for k, v in touches.items()])
            except Exception as e:
                log.warning("safety loop: %s", e)
            await asyncio.sleep(0.5)

    def opener_file(self, url) -> Path:
        """A 0600 page in the 0700 state directory that forwards the browser to the tokenised link. Browsers get
        their start URL on the command line, which other local users can read (/proc/<pid>/cmdline, ps)."""
        p = self.store.home / "open.html"
        write_private(p, "<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer><title>TABULA</title>"
                         f"<script>location.replace({json.dumps(url)});</script>"
                         "<p>Opening the desk… (the link printed in the host window works too)</p>")
        return p

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        bind = "0.0.0.0" if self.cfg["lan"] else self.cfg["bind"]
        port = int(self.cfg["port"])
        async with ws_serve(self.handler, bind, port, process_request=self.process_request, max_size=16 * 2 ** 20, compression=None, ping_interval=20, ping_timeout=30):
            for coro in (self.focus_loop(), self.clip_loop(), self.telemetry_loop(), self.safety_loop()):
                asyncio.ensure_future(coro)
            if websockets is not None:
                asyncio.ensure_future(self.obs.run())
            if self.args.sense:
                try:
                    await asyncio.to_thread(self.start_sense, self.args.sense, self.args.tangibles)
                except Exception as e:
                    log.error("sensing failed to start: %s", e)
            url = f"http://127.0.0.1:{port}/#t={self.store.token}"
            lan = ""
            if self.cfg["lan"]:
                ips = sorted(a for a in self.addrs if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a) and not a.startswith("127."))
                lan = "".join(f"  LAN   http://{ip}:{port}/#t={self.store.token}\n" for ip in ips) or "  LAN   (no IPv4 address found)\n"
            print(f"\n  TABULA-Ω host {VERSION}  ·  {OS}  ·  input {self.inp.name}{'  (DRY-RUN: nothing is injected)' if self.dry else ''}\n"
                  f"  open  {url}\n{lan}"
                  f"        the #t=… part is this run's token: it never leaves the browser, and the page does not contain it\n"
                  f"  config {self.store.cfg_path}\n  state: DISARMED — arm from the page's TRIBUNAL once every critic agrees\n", flush=True)
            if not self.args.no_browser:
                try:
                    webbrowser.open(self.opener_file(url).as_uri())       # argv carries a file path, not the token
                except Exception:
                    pass
            await asyncio.Future()


# ==================================================================================================
# self-test
# ==================================================================================================
def selftest(verbose=True) -> int:
    results = []

    def check(name, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            results.append((name, True, detail, (time.perf_counter() - t0) * 1000))
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}", (time.perf_counter() - t0) * 1000))

    def chords():
        assert resolve_chord("mod+shift+p", "win") == [(frozenset({"ctrl", "shift"}), "p")]
        assert resolve_chord("mod+shift+p", "mac") == [(frozenset({"cmd", "shift"}), "p")]
        assert resolve_chord({"win": "win+tab", "mac": "ctrl+up"}, "mac") == [(frozenset({"ctrl"}), "up")]
        assert resolve_chord({"win": "win+v"}, "linux") == []
        assert resolve_chord(["mod+k", "z"], "linux") == [(frozenset({"ctrl"}), "k"), (frozenset(), "z")]
        assert resolve_chord("super", "linux") == [(frozenset(), "win")]
        assert resolve_chord("mod+=", "win") == [(frozenset({"ctrl"}), "=")]
        return "per-OS maps, sequences, lone modifiers"

    def homog():
        rng = np.random.default_rng(1)
        Ht = [[1.2, 0.1, 30], [-0.05, 0.9, 12], [1e-4, 2e-4, 1]]
        src = rng.uniform(0, 500, (60, 2))
        dst = [h_apply(Ht, *p) for p in src]
        H = homography_dlt(src, dst)
        err = max(math.dist(h_apply(H, *p), q) for p, q in zip(src, dst))
        assert err < 1e-6, err
        dst2 = [q if i % 4 else (q[0] + 80, q[1] - 50) for i, q in enumerate(dst)]
        H2, idx, rms = homography_ransac(src, dst2, thresh=2.0)
        assert len(idx) >= 44 and rms < 1e-3, (len(idx), rms)
        return f"DLT {err:.1e} px; RANSAC kept {len(idx)}/60 with 25 % outliers"

    def graycode():
        W, H, step = 640, 360, 8
        plan = gray_plan(W, H, step)
        cw, ch = 320, 200
        Ht = homography_dlt([(0, 0), (cw, 0), (cw, ch), (0, ch)], [(20, 15), (610, 40), (630, 350), (5, 330)])      # camera px → surface px
        yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float64) + 0.5
        w = Ht[2][0] * xx + Ht[2][1] * yy + Ht[2][2]
        sx = (Ht[0][0] * xx + Ht[0][1] * yy + Ht[0][2]) / w
        sy = (Ht[1][0] * xx + Ht[1][1] * yy + Ht[1][2]) / w
        cx, cy = np.floor(sx / step).astype(int), np.floor(sy / step).astype(int)
        gxv, gyv = cx ^ (cx >> 1), cy ^ (cy >> 1)
        rng = np.random.default_rng(2)
        frames = []
        for p in plan["pats"]:
            if p["kind"] == "black":
                img = np.full((ch, cw), 20.0)
            elif p["kind"] == "white":
                img = np.full((ch, cw), 220.0)
            else:
                g, nb = (gxv, plan["bx"]) if p["axis"] == "x" else (gyv, plan["by"])
                bit = (g >> (nb - 1 - p["b"])) & 1
                if p["inv"]:
                    bit = 1 - bit
                img = 20.0 + 200.0 * bit
            frames.append((img + rng.normal(0, 3, img.shape)).astype(np.float32))
        col, row, valid = gray_decode(plan, frames)
        cam, surf = gray_correspondences(plan, col, row, valid)
        He, idx, rms = homography_ransac(cam, surf, thresh=step)
        err = max(math.dist(h_apply(He, *p), h_apply(Ht, *p)) for p in [(40, 30), (160, 100), (300, 180)])
        assert err < 2.0, err
        return f"{len(plan['pats'])} patterns, {len(cam)} cells, max error {err:.2f} surface px"

    def osc():
        pkt = osc_bundle(osc_message("/tuio/2Dcur", "alive", 1, 2), osc_message("/tuio/2Dcur", "set", 1, 0.25, 0.5, 0.0, 0.0, 0.0), osc_message("/x", "hi", True))
        m = osc_parse(pkt)
        assert m[0] == ("/tuio/2Dcur", ["alive", 1, 2]) and abs(m[1][1][2] - 0.25) < 1e-6 and m[2] == ("/x", ["hi", True]), m
        return "bundle round-trip"

    def euro():
        f = OneEuro(1.0, 0.0, 1.0)
        ys = [f(10.0 if i > 5 else 0.0, i / 60) for i in range(120)]
        assert ys[5] == 0 and 9.9 < ys[-1] <= 10.0 and ys[6] < 5, ys[:8]
        return f"step response settles to {ys[-1]:.3f}"

    def engine():
        src = SyntheticDepth(hz=30)
        eng = TouchEngine(default_config()["sense"], (1000.0, 562.5), 800.0)
        downs, hovers, frames, ms = [], 0, 0, []
        for i in range(30 + 360):
            d, _ = src.read()
            t = i / 30
            r = eng.step(d, t)
            if r is None:
                continue
            frames += 1
            ms.append(eng.stats["ms"])
            for c in r["contacts"]:
                if c["phase"] == "down":
                    best = min(src.truth, key=lambda q: math.dist((q[0] * 1000, q[1] * 562.5), (c["x"] * 1000, c["y"] * 562.5)))
                    downs.append((math.dist((best[0] * 1000, best[1] * 562.5), (c["x"] * 1000, c["y"] * 562.5)), best[2]))
                elif c["phase"] == "hover":
                    hovers += 1
            if src.frame_i > 40:
                assert len(r["objects"]) >= 1, "mug not reported as an object"
        expected = 2 * (360 / 30) / 1.6
        good = [e for e, z in downs if e < 15 and z < 20]
        assert len(good) >= 0.7 * expected, (len(good), expected, downs[:6])
        assert len(downs) - len(good) <= 2, downs
        return f"{len(good)}/{expected:.0f} taps, mean err {sum(e for e, _ in downs) / max(1, len(downs)):.1f} mm, {np.median(ms):.1f} ms/frame"

    def backend():
        b = DryRunBackend()
        for mods, key in resolve_chord(["mod+s", "alt+tab"], "win"):
            b.chord(mods, key)
        b.text("hé")
        b.touch_frame([{"id": "a", "x": 10, "y": 20, "phase": "down"}])
        b.release_all()
        kinds = [e[1] for e in b.events]
        assert kinds.count("key") == 8 and "text" in kinds and kinds.count("touch") == 2, kinds
        return f"{len(b.events)} dry events"

    def jpeg():
        img = synthetic_screen(640, 360, 1.0)
        j = encode_jpeg(img, 70)
        assert j and j[:2] == b"\xff\xd8"
        return f"{len(j) / 1024:.0f} KB test card"

    def aruco():
        d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)
        canvas = np.full((400, 700), 255, np.uint8)
        for n, mid in enumerate((0, 7, 42)):
            canvas[100:260, 40 + n * 220:200 + n * 220] = cv2.resize(cv2.aruco.generateImageMarker(d, mid, 8), (160, 160), interpolation=cv2.INTER_NEAREST)
        det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
        _, ids, _ = det.detectMarkers(canvas)
        got = sorted(int(i) for i in ids.ravel()) if ids is not None else []
        assert got == [0, 7, 42], got
        svg = marker_sheet_svg(range(4))
        assert svg.startswith("<svg")
        return "MIP 36h12 generate → detect → [0, 7, 42]"

    def policy():
        bad = [["bash", "-lc", "x"], ["pwsh", "-enc", "AAA"], ["python3", "-c", "1"], ["/usr/bin/env", "sh", "-c", "x"], ["node", "-e", "1"],
               ["cmd.exe", "/c", "dir"], ["sudo", "ls"], ["C:\\Windows\\System32\\mshta.exe", "x"], ["ls", "*.txt"],
               ["node", "--eval=1"], ["node", "-pe", "1"], ["pwsh", "-en", "AAA"], ["cmd", "/cdir"], ["env", "-S", "sh -c x"], ["deno", "eval", "1"],
               ["git", "-c", "alias.x=!sh", "x"], ["git", "-c", "core.sshCommand=evil", "fetch"], ["awk", "BEGIN{}"], ["timeout", "5", "bash", "-c", "x"]]
        good = [["code"], ["git", "status", "--short"], ["git", "-C", "~/repo", "status"], ["bash", "--norc", "script.sh"], ["open", "-a", "Terminal"],
                ["wt.exe"], ["ollama", "ps"], ["nice", "-n", "5", "make"], ["python3", "-m", "http.server"]]
        assert all(allowlist_problem(a) for a in bad), [a for a in bad if not allowlist_problem(a)]
        assert not any(allowlist_problem(a) for a in good), [(a, allowlist_problem(a)) for a in good if allowlist_problem(a)]
        secrets_ = ["k7#Qp!2vXz9$Lm4w", "Tr0ub4dor&3", "sk-ant-api03-abcdefghij", "ghp_0123456789abcdefABCDEF", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.x"]
        plain = ["ngap && ngap.procedureCode == 15", "ws://127.0.0.1:7777/ws", "hello world", "git commit -am x", "correcthorsebatterystaple", "/home/marco/x.py", "2026-09-30"]
        assert all(looks_secret(x) for x in secrets_), [x for x in secrets_ if not looks_secret(x)]
        assert not any(looks_secret(x) for x in plain), [x for x in plain if looks_secret(x)]
        us = type("L", (), {"layout": "us"})()
        pt = type("L", (), {"layout": "pt"})()
        assert UinputBackend.can_type(us, "a@b.c\n") and not UinputBackend.can_type(us, "hé") and not UinputBackend.can_type(pt, "abc")
        assert not UinputBackend.can_type(type("L", (), {"layout": "us+dvorak"})(), "abc")
        assert _dumps({"x": float("nan"), "y": [float("inf"), 1.5]}) == '{"x": null, "y": [null, 1.5]}'
        return f"{len(bad)} risky argv refused, {len(good)} plain accepted · secrets masked {len(secrets_)}/{len(secrets_)}, {len(plain)} plain kept · uinput types only on 'us'"

    def guards():
        armed = [False]
        g = Guarded(DryRunBackend(), lambda: armed[0])
        try:
            g.chord(frozenset(), "a")
            raise AssertionError("injected while disarmed")
        except Aborted:
            pass
        g.button("left", False)                                         # releases always pass
        g.touch_frame([{"id": "a", "x": 1, "y": 2, "phase": "up"}])
        armed[0] = True
        g.text("ok")
        armed[0] = False
        tc = TapCal()
        for i in range(60):                                             # finger held still on one spot for 2 s
            tc.feed([(123.0, 45.0)], i / 30)
        assert len(tc.samples) == 1, f"TapCal took {len(tc.samples)} samples without a lift"
        for i in range(4):
            tc.feed([], 2 + i / 30)
        for i in range(25):
            tc.feed([(300.0, 45.0)], 3 + i / 30)
        assert len(tc.samples) == 2, len(tc.samples)
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d))
            st.override("lan", True)
            st.override("port", 9999)
            st.save()
            disk = json.loads((Path(d) / "config.json").read_text())
            assert disk["lan"] is False and disk["port"] == 7777 and st.cfg["lan"] is True, disk
            if OS != "win":
                assert (os.stat(d).st_mode & 0o777) == 0o700 and (os.stat(Path(d) / "config.json").st_mode & 0o777) == 0o600
            st.audit("act", a={"do": "text", "s": redact("hunter2")})
            assert "hunter2" not in (Path(d) / "audit.log").read_text()
        tin = TUIOIn(0)
        port = tin.sock.getsockname()[1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"#bundle\x00garbage", ("127.0.0.1", port))
        s.sendto(osc_message("/tuio/2Dcur", "set", 7, 0.25, 0.5, 0.0, 0.0, 0.0), ("127.0.0.1", port))
        assert tin.poll() is True and tin.poll() is True and 7 in tin.cur, tin.cur
        tin.close()
        tin2 = TUIOIn(port)                                              # the port is free again after close()
        tin2.close()
        s.close()
        n = sum(1 for e in g._inner.events if e[1] in ("key", "text"))
        assert n == 1, list(g._inner.events)
        return "disarmed injection refused, releases pass · TapCal needs a lift · CLI overrides not saved · 0700/0600 · audit redacted · TUIO survives garbage + rebinds"

    check("chord parser", chords)
    check("allow-list / secrets / layout policy", policy)
    check("guards: PANIC, TapCal, store, TUIO", guards)
    if np is not None:
        check("homography DLT + RANSAC", homog)
        check("Gray-code decode", graycode)
    check("OSC / TUIO codec", osc)
    check("One Euro filter", euro)
    if np is not None and cv2 is not None:
        check("depth touch engine (synthetic arms)", engine)
        check("ArUco tokens", aruco)
    check("dry-run backend", backend)
    if np is not None:
        check("JPEG portal frame", jpeg)
    ok = all(r[1] for r in results)
    if verbose:
        print(f"\nTABULA-Ω host self-test · python {platform.python_version()} · {OS}")
        for name, good, detail, ms in results:
            print(f"  {'PASS' if good else 'FAIL'}  {name:<38} {ms:7.1f} ms  {detail}")
        print("  missing optional modules:", ", ".join(n for n, m in (("numpy", np), ("opencv", cv2), ("psutil", psutil), ("mss", mss_mod), ("pyperclip", pyperclip)) if m is None) or "none")
        print("  RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


# ==================================================================================================
# CLI
# ==================================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(prog="tabula_host.py", description="TABULA-Ω host bridge — serves the projected desk and drives this computer from it.")
    ap.add_argument("--port", type=int, help="HTTP/WebSocket port (default 7777)")
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (token + origin checks still apply)")
    ap.add_argument("--dry-run", action="store_true", help="log every action, inject nothing")
    ap.add_argument("--backend", default="auto", choices=["auto", "windows", "mac", "uinput", "x11", "pynput", "dry"], help="input injection backend")
    ap.add_argument("--sense", help="synthetic | realsense | orbbec | k4a | freenect2 | lightplane:N | tuio | replay:file.npz | none")
    ap.add_argument("--tangibles", type=int, default=-1, help="camera index for ArUco tokens / scan (-1 = off)")
    ap.add_argument("--tuio-in", type=int, nargs="?", const=3333, help="accept TUIO 1.1 on this UDP port (use with --sense tuio)")
    ap.add_argument("--tuio-out", help="send desk touches as TUIO to HOST:PORT")
    ap.add_argument("--home", help="state directory (default ~/.tabula)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the page")
    ap.add_argument("--print-tokens", metavar="FILE.svg", help="write a printable ArUco token sheet and exit")
    ap.add_argument("--selftest", action="store_true", help="run the built-in self-test and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    class _NoToken(logging.Filter):
        def filter(self, rec):
            msg = rec.getMessage()
            if "token=" in msg or "#t=" in msg:
                rec.msg, rec.args = re.sub(r"(token=|#t=)[A-Za-z0-9_\-]+", r"\1…", msg), ()
            return True
    for h in logging.getLogger().handlers:
        h.addFilter(_NoToken())
    if args.selftest:
        return selftest()
    if args.print_tokens:
        Path(args.print_tokens).write_text(marker_sheet_svg())
        print("wrote", args.print_tokens)
        return 0
    if websockets is None:
        print("TABULA needs the 'websockets' package ≥ 13:  pip install websockets", file=sys.stderr)
        return 2
    store = Store(Path(args.home).expanduser() if args.home else HOME)
    if args.port:                                                      # run-only: never written back to config.json
        store.override("port", args.port)
    if args.lan:
        store.override("lan", True)
    if args.tuio_out:
        h, p = args.tuio_out.rsplit(":", 1)
        store.override("tuio_out", [h, int(p)])
    host = Host(args, store)
    try:
        asyncio.run(host.serve())
    except KeyboardInterrupt:
        pass
    finally:
        try:
            host.inp.release_all()
        except Exception:
            pass
        store.audit("stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
