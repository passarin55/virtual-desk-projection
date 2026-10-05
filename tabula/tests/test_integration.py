#!/usr/bin/env python3
"""End-to-end: tabula_host.py (--dry-run --sense synthetic) serves the page; a headless browser opens the
host's #t= link, receives synthetic depth touches, arms through the gate, drives the palette, streams the
PORTAL. Security: the page never contains the token, framing is refused, bad tokens / foreign Host headers /
foreign or missing Origins are rejected, input is bound to the arming window, PANIC aborts a running key
sequence, saved page state cannot break the page, CLI flags are not persisted, the audit log is redacted,
and LAN mode keeps a Host/Origin allow-list."""
import asyncio, json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "dist" / "tabula_host.py"
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def health(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
        return json.loads(r.read())


def http_get(port, path, host_hdr=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host_hdr} if host_hdr else {})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), ""


async def ws_try(port, token, origin, send=None):
    from websockets.asyncio.client import connect
    try:
        async with connect(f"ws://127.0.0.1:{port}/ws?token={token}", origin=origin, open_timeout=3) as ws:
            m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if send is None:
                return m.get("t")
            await ws.send(json.dumps(send))
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if r.get("id") == send.get("id"):
                    return r
    except Exception as e:
        return "rejected:" + type(e).__name__


def stalled_client(port, token, stop):
    """a window that opens a PORTAL and then never reads (sleeping laptop, frozen tab): the host must drop it, not wait on it"""
    async def run():
        from websockets.asyncio.client import connect
        async with connect(f"ws://127.0.0.1:{port}/ws?token={token}", origin=f"http://127.0.0.1:{port}", max_queue=1, open_timeout=3) as ws:
            await ws.send(json.dumps({"t": "portal", "op": "start", "target": {"follow": True}, "fps": 30, "maxW": 1920, "q": 90}))
            while not stop.is_set():
                await asyncio.sleep(0.2)
    try:
        asyncio.run(run())
    except Exception:
        pass


def arun(coro):
    """asyncio.run from a worker thread (Playwright's sync API owns this thread's event loop)"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def start_host(port, home, *extra):
    proc = subprocess.Popen([sys.executable, str(HOST), "--dry-run", "--port", str(port), "--home", home, "--no-browser", *extra],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        try:
            return proc, health(port)
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    raise SystemExit("host did not start:\n" + proc.communicate(timeout=5)[0])


def main():
    port = free_port()
    home = tempfile.mkdtemp(prefix="tabula-home-")
    proc, h = start_host(port, home, "--sense", "synthetic")
    ok = True
    try:
        print("health:", h)
        token = Path(home, "token").read_text().strip()

        # ---- security: the page never carries the token; no framing; DNS-rebinding guard; token + Origin checks
        st, hdr, body = http_get(port, "/")
        assert st == 200 and token not in body, "token inlined in the page"
        assert "frame-ancestors 'none'" in hdr.get("Content-Security-Policy", "") and hdr.get("X-Frame-Options") == "DENY", hdr
        assert http_get(port, "/", "evil.example:%d" % port)[0] == 421, "Host header not enforced"
        assert arun(ws_try(port, "wrong", f"http://127.0.0.1:{port}")).startswith("rejected"), "bad token accepted"
        assert arun(ws_try(port, token, "https://evil.example")).startswith("rejected"), "foreign origin accepted"
        assert arun(ws_try(port, token, None)).startswith("rejected"), "Origin-less client accepted"
        assert arun(ws_try(port, token, f"http://localhost:{port}")) == "welcome"
        print("security: no token in page · frame-ancestors none · Host guard 421 · bad token / foreign origin / no origin rejected · good client welcomed")

        with sync_playwright() as p:
            b = p.chromium.launch(args=ARGS)
            pg = b.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(f"http://127.0.0.1:{port}/#t={token}")                 # the link the host opens / prints
            pg.wait_for_function("window.T && T.host && T.host.mode==='live' && T.host.connected", timeout=15000)
            assert pg.evaluate("location.hash") == "" and pg.evaluate("sessionStorage.getItem('tabula.t')") == token, "token not scrubbed from the URL"
            info = pg.evaluate("T.host.info")
            print("welcome:", {k: info[k] for k in ("os", "input", "dry", "sense", "caps")}, "· token moved from #t= to sessionStorage")
            assert info["dry"] and "touch" in info["caps"]

            # ---- synthetic depth touches arrive and flow through the input hub
            pg.evaluate("(()=>{ window.__ups=[]; T.bus.on('input:up', c=>{ if(c.src==='host') window.__ups.push([c.x,c.y,c.dur]) }); })()")   # IIFE: a returned function would be invoked by Playwright
            pg.wait_for_function("window.__ups.length >= 3", timeout=20000)
            ups = pg.evaluate("window.__ups")
            print("host depth taps seen on the desk:", len(ups), "first:", [round(v, 1) for v in ups[0]])
            pg.wait_for_function("T.engine.hostObjects.length >= 1", timeout=8000)
            print("objects from depth:", pg.evaluate("T.engine.hostObjects.map(o=>o.kind+'@'+Math.round(o.x)+','+Math.round(o.y))"))

            # ---- telemetry
            pg.wait_for_function("T.host.telemetry && T.host.telemetry.cpu !== undefined", timeout=5000)

            # ---- not armed → actions refused
            r = pg.evaluate("T.host.request({t:'act', a:{do:'key', c:'mod+s'}})")
            assert r["ok"] is False and "not armed" in r["err"], r
            # ---- gate: stale / FAIL reports refused, a unanimous fresh report arms
            r = pg.evaluate("T.host.arm(true, {verdicts:[{id:'optics', v:'FAIL'}], strict:true, at:Date.now()})")
            assert not r["ok"], r

            def arm():
                r = pg.evaluate("T.host.arm(true, T.tribunal.gate().report)")
                if not r["ok"]:
                    pg.evaluate("T.tribunal.run().filter(c=>c.v==='WARN').forEach(c=>T.tribunal.ack(c.id,true))")
                    time.sleep(0.3)
                    r = pg.evaluate("T.host.arm(true, T.tribunal.gate().report)")
                assert r["ok"], r
                pg.wait_for_function("T.host.armed === true", timeout=3000)
            arm()
            print("armed with the live TRIBUNAL report (WARNs acknowledged as the operator would)")

            # ---- input is bound to the arming window: another authenticated client cannot inject
            r = arun(ws_try(port, token, f"http://127.0.0.1:{port}", {"t": "act", "id": "x1", "a": {"do": "key", "c": "mod+s"}}))
            assert isinstance(r, dict) and not r["ok"] and "armed" in r["err"], r
            print("second client while armed →", r["err"])
            fake = {"verdicts": [{"id": "x", "v": "PASS"}], "at": time.time() * 1000, "strict": True}
            r = arun(ws_try(port, token, f"http://127.0.0.1:{port}", {"t": "arm", "id": "a2", "on": True, "gate": fake}))
            assert isinstance(r, dict) and not r["ok"] and "another window" in r["err"], r
            print("second client tries to take over the arming →", r["err"])

            # ---- tap the palette on the desk preview (real pointer path) → host injects (dry) a chord
            pg.evaluate("T.engine.setWorkspace('DEV', true); T.engine.layout()")
            time.sleep(0.5)
            cell = pg.evaluate("(()=>{const w=T.engine.get('palette'); w.compute(); const c=w.cells.find(c=>c.item.a&&c.item.a.do==='key'); return {x:c.r.x+c.r.w/2, y:c.r.y+c.r.h/2, l:c.item.l}})()")
            box = pg.locator("#deskView").bounding_box()
            W, H = pg.evaluate("[T.cfg.desk.w, T.cfg.desk.h]")
            pg.mouse.click(box["x"] + cell["x"] / W * box["width"], box["y"] + cell["y"] / H * box["height"])
            time.sleep(0.8)
            ev = health(port)["dry_events"]
            keys = [e for e in ev if e[1] == "key"]
            print("palette", repr(cell["l"]), "→ host dry key events:", [(e[2], e[3]) for e in keys[-6:]])
            assert keys, "no key events reached the host"

            # ---- text + trackpad + wheel through the host
            pg.evaluate("T.actions.run({do:'text', s:'hello desk'})"); time.sleep(0.3)
            pg.evaluate("T.host.ptr({op:'rel', dx:12, dy:-4}); T.host.ptr({op:'wheel', dy:2, mods:'ctrl'}); T.host.ptr({op:'click', btn:'right'})"); time.sleep(0.4)
            kinds = [e[1] for e in health(port)["dry_events"]]
            assert "text" in kinds and "rel" in kinds and "wheel" in kinds and "button" in kinds, kinds[-12:]
            # ---- OS touch frame (portal touch mode path) + the stuck-touch watchdog
            pg.evaluate("T.host.send({t:'touch', contacts:[{id:'a',x:100,y:200,phase:'down'},{id:'b',x:140,y:200,phase:'down'}]}); T.host.send({t:'touch', contacts:[{id:'a',x:100,y:200,phase:'up'},{id:'b',x:140,y:200,phase:'up'}]})"); time.sleep(0.3)
            assert any(e[1] == "touch" for e in health(port)["dry_events"])
            pg.evaluate("T.host.send({t:'touch', contacts:[{id:'z',x:10,y:20,phase:'down'}]})")          # …and the page goes silent
            time.sleep(4.2)
            lifted = [e for e in health(port)["dry_events"] if e[1] == "touch" and ["z", "up"] in e[2]]
            assert lifted, "watchdog did not lift a silent touch"
            print("stuck-touch watchdog lifted a contact the page stopped updating")
            # ---- allow-list: unknown launch refused, known run returns output (dry)
            r = pg.evaluate("T.host.request({t:'act', a:{do:'launch', id:'rm_rf'}})"); assert not r["ok"] and "allow-list" in r["err"], r
            r = pg.evaluate("T.host.request({t:'act', a:{do:'run', id:'ollama_ps'}})"); assert r["ok"], r
            print("allow-list: unknown launch refused · run →", r.get("out"))
            # ---- limits: an oversized key sequence is refused outright
            r = pg.evaluate("T.host.request({t:'act', a:{do:'key', c: Array(40).fill('left')}})"); assert not r["ok"] and "at most" in r["err"], r

            # ---- PORTAL: frames stream (synthetic screen in a headless container)
            pg.wait_for_function("T.engine.get('portal').frame && T.engine.get('portal').frame.hdr.seq >= 3", timeout=10000)
            hdr = pg.evaluate("T.engine.get('portal').frame.hdr")
            print("portal frames:", {k: hdr[k] for k in ("seq", "w", "h", "rect", "sim")})

            # ---- VLM with no model server → graceful error
            r = pg.evaluate("T.host.request({t:'vlm', mode:'ocr', img:'data:image/jpeg;base64,/9j/2w=='}, 20000)")
            print("vlm without a local model:", r.get("ok"), (r.get("err") or "")[:90])
            assert r["ok"] is False

            # ---- PANIC disarms
            pg.evaluate("T.host.panic('test')"); time.sleep(0.4)
            assert health(port)["armed"] is False

            # ---- PANIC is out of band: it lands while a 30-chord sequence (~1 s) is being typed and aborts the rest
            arm()
            r = pg.evaluate("""(async () => {
              const p = T.host.request({ t: 'act', a: { do: 'key', c: Array(30).fill('down') } }, 8000);
              await T.sleep(200); const t0 = performance.now(); T.host.panic('oob test');
              const r = await p; r.ms = performance.now() - t0; return r; })()""")
            n_down = sum(1 for e in health(port)["dry_events"] if e[1] == "key" and e[2] == "down" and e[3] is True)
            print(f"PANIC during a 30-chord sequence → ack after {r['ms']:.0f} ms: {r.get('err')} · chords typed ≈ {n_down}")
            assert not r["ok"] and "aborted" in r["err"] and r["ms"] < 1000 and n_down < 20, (r, n_down)

            # ---- a window that stops reading can neither block arming/PANIC for the others nor stay connected
            stop = threading.Event()
            th = threading.Thread(target=stalled_client, args=(port, token, stop), daemon=True); th.start()
            time.sleep(3.0)                                                         # its socket buffers are full by now
            t0 = time.time(); arm(); t_arm = time.time() - t0
            t0 = time.time(); pg.evaluate("T.host.panic('stall test')")
            while health(port)["armed"] and time.time() - t0 < 3:
                time.sleep(0.05)
            t_panic = time.time() - t0
            for _ in range(40):
                if health(port)["clients"] == 1:
                    break
                time.sleep(0.25)
            print(f"stalled window: arm took {t_arm:.2f} s, PANIC {t_panic:.2f} s · stalled window dropped → clients {health(port)['clients']}")
            assert t_arm < 2.0 and t_panic < 1.0 and health(port)["clients"] == 1, (t_arm, t_panic, health(port)["clients"])
            stop.set()

            # ---- nothing in saved page state can carry a token into the served page
            pg.evaluate("T.host.request({t:'cfg', op:'save', cfg: Object.assign(T.cfgPublic(), {host: {url: '', mode: 'live', token: 'LEAKME0123456789abcdef'}})})")
            time.sleep(0.3)
            assert "LEAKME" not in http_get(port, "/")[2] and "LEAKME" not in Path(home, "page-state.json").read_text()
            print("a token pushed into page state is neither stored nor served")

            # ---- saved page state cannot break the page (an HTML-comment/script opener inside a macro)
            nasty = "x<!--<script>'\"&</script>"
            pg.evaluate(f"(()=>{{ const c=T.deepClone(T.cfg); c.macros=[{{id:'n',l:{json.dumps(nasty)},g:'dev',steps:[{{do:'text',s:{json.dumps(nasty)}}}]}}]; return T.host.request({{t:'cfg', op:'save', cfg:c}}); }})()")
            pg.reload()
            pg.wait_for_function("window.T && T.host && T.host.connected", timeout=15000)       # token survives a reload (sessionStorage)
            assert pg.evaluate("T.cfg.macros[0].l") == nasty
            print("page state with", repr(nasty), "round-trips; page boots and reconnects after reload")

            pg.screenshot(path=str(Path(tempfile.gettempdir()) / "tabula_live.png"))
            b.close()
            errs = [e for e in errors if "fonts.g" not in e and "ERR_" not in e]
            print("page errors:", errs[:5]); assert not errs
        audit_txt = Path(home, "audit.log").read_text()
        kinds = [json.loads(l)["kind"] for l in audit_txt.splitlines()]
        print("audit log kinds:", sorted(set(kinds)))
        assert "arm" in kinds and "act" in kinds and "disarm" in kinds and "reject" in kinds
        assert "hello desk" not in audit_txt, "typed text in the audit log"
        disk = json.loads(Path(home, "config.json").read_text())
        assert disk["port"] == 7777, "--port was persisted"
        if os.name != "nt":
            assert (os.stat(home).st_mode & 0o777) == 0o700 and (os.stat(Path(home, "audit.log")).st_mode & 0o777) == 0o600
        print("audit redacted · --port not persisted · home 0700, audit.log 0600")
    except Exception:
        ok = False
        raise
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=5)[0]
        except Exception:
            out = ""
        if not ok:
            print("---- host output ----\n" + out[-4000:])

    # ---- LAN mode: still a Host/Origin allow-list, still no token in the page, CLI flag not persisted
    port2, home2 = free_port(), tempfile.mkdtemp(prefix="tabula-lan-")
    proc2, _ = start_host(port2, home2, "--lan")
    try:
        tok2 = Path(home2, "token").read_text().strip()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9)); ip = s.getsockname()[0]
        except OSError:
            ip = None
        s.close()
        st, _, body = http_get(port2, "/")
        assert st == 200 and tok2 not in body
        assert http_get(port2, "/", f"attacker.example:{port2}")[0] == 421, "LAN mode accepted a foreign Host"
        assert arun(ws_try(port2, tok2, f"http://attacker.example:{port2}")).startswith("rejected"), "LAN mode accepted a foreign Origin"
        if ip:
            assert http_get(port2, "/", f"{ip}:{port2}")[0] == 200
            assert arun(ws_try(port2, tok2, f"http://{ip}:{port2}")) == "welcome"
        assert json.loads(Path(home2, "config.json").read_text())["lan"] is False, "--lan was persisted"
        print(f"LAN mode: foreign Host 421 · foreign Origin rejected · own address {ip or '(none)'} accepted · --lan not persisted")
    finally:
        proc2.terminate()
        proc2.communicate(timeout=5)
    print("INTEGRATION OK")


if __name__ == "__main__":
    main()
