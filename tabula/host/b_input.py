

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
