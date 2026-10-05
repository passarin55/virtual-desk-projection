

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
