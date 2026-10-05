

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
