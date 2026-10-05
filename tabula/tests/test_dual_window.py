#!/usr/bin/env python3
"""Console + projector window: the #projector window takes the lead (engine, host link, camera);
the console follows (preview frames, status), forwards clicks and commands by RPC, and takes the lead
back when the projector window closes. A second console never steals the lead from a console that is
already driving the desk. Served by the host so all windows share an origin; the token rides the #t= link."""
import json, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def main():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    home = tempfile.mkdtemp(prefix="tabula-dual-")
    proc = subprocess.Popen([sys.executable, str(ROOT / "dist" / "tabula_host.py"), "--dry-run", "--port", str(port), "--home", home, "--no-browser"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    health = lambda: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read())
    try:
        for _ in range(40):
            try:
                health(); break
            except Exception:
                time.sleep(0.25)
        with sync_playwright() as p:
            b = p.chromium.launch(args=ARGS)
            ctx = b.new_context(viewport={"width": 1400, "height": 900})
            errs = []
            con = ctx.new_page(); con.on("pageerror", lambda e: errs.append("console: " + str(e)))
            token = Path(home, "token").read_text().strip()
            con.goto(f"http://127.0.0.1:{port}/#t={token}")
            con.wait_for_function("window.T && T.host && T.host.connected && T.host.mode==='live'", timeout=15000)
            assert health()["clients"] == 1
            print("console alone: leader =", con.evaluate("T.link.isLeader()"))

            proj = ctx.new_page(); proj.on("pageerror", lambda e: errs.append("projector: " + str(e)))
            proj.goto(f"http://127.0.0.1:{port}/#projector&t={token}")   # what the console's "Projector window" button opens
            proj.wait_for_function("window.T && T.link && T.link.isLeader() && T.host.connected", timeout=15000)
            con.wait_for_function("!T.link.isLeader()", timeout=5000)
            for _ in range(20):                                    # the console drops its host link once it sees the projector
                if health()["clients"] == 1:
                    break
                time.sleep(0.25)
            print("with projector: console leader =", con.evaluate("T.link.isLeader()"), "· projector leader =", proj.evaluate("T.link.isLeader()"), "· host clients =", health()["clients"])
            assert health()["clients"] == 1, "both windows are talking to the host"
            con.wait_for_function("T.link.pvBmp && T.link.remote && T.link.remote.host.connected", timeout=8000)
            print("console mirrors: preview", con.evaluate("[T.link.pvBmp.width, T.link.pvBmp.height]"), "· remote ws", con.evaluate("T.link.remote.engine.ws"))

            # click the palette on the console's (follower) preview → executes in the projector window
            proj.evaluate("(()=>{ window.__acts=[]; const f=T.actions.run.bind(T.actions); T.actions.run=(a,c)=>{ window.__acts.push(T.actions.describe(a)); return f(a,c); }; })()")
            cell = proj.evaluate("(()=>{const w=T.engine.get('palette'); w.compute(); const c=w.cells[0]; return {x:c.r.x+c.r.w/2, y:c.r.y+c.r.h/2, l:c.item.l}})()")
            box = con.locator("#deskView").bounding_box()
            W, H = con.evaluate("[T.cfg.desk.w, T.cfg.desk.h]")
            con.mouse.click(box["x"] + cell["x"] / W * box["width"], box["y"] + cell["y"] / H * box["height"])
            time.sleep(0.8)
            acts = proj.evaluate("window.__acts")
            print("console click on", repr(cell["l"]), "→ projector acted:", acts[:3])
            assert acts, "forwarded click did nothing"

            # workspace + config RPC, SIM Gray-code executed by the leader
            con.evaluate("T.call('setWorkspace',{name:'STUDIO'})")
            proj.wait_for_function("T.engine.ws === 'STUDIO'", timeout=5000)
            con.evaluate("T.call('patchCfg',{patch:{desk:{handed:'left'}}})")
            proj.wait_for_function("T.cfg.desk.handed === 'left'", timeout=5000)
            con.wait_for_function("T.cfg.desk.handed === 'left'", timeout=5000)       # config flows back to the follower
            res = con.evaluate("T.call('gray',{src:'sim',step:16}).then(r=>({ok:r.ok, mm:r.rmsMm, truth:r.truthMm}))")
            print("Gray-code run by the leader for the console:", res)
            assert res["ok"]

            # PANIC from the follower console must not wait for a busy leader: it opens its own socket to the host
            r = proj.evaluate("T.host.arm(true, T.tribunal.gate().report)")
            if not r["ok"]:
                proj.evaluate("T.tribunal.run().filter(c=>c.v==='WARN').forEach(c=>T.tribunal.ack(c.id,true))"); time.sleep(0.3)
                r = proj.evaluate("T.host.arm(true, T.tribunal.gate().report)")
            assert r["ok"] and health()["armed"], r
            proj.evaluate("setTimeout(() => { const t = performance.now(); while (performance.now() - t < 4000) {} }, 0)")   # leader hangs for 4 s
            time.sleep(0.2)
            t0 = time.time(); con.evaluate("document.getElementById('btnPanic').click()")
            while health()["armed"] and time.time() - t0 < 5:
                time.sleep(0.05)
            dt = time.time() - t0
            print(f"PANIC from the follower while the leader hangs: host disarmed after {dt:.2f} s")
            assert not health()["armed"] and dt < 1.5, dt
            time.sleep(4.2)                                                     # let the leader recover

            # close the projector → console leads again and reconnects to the host
            proj.close()
            con.wait_for_function("T.link.isLeader() && T.host.connected", timeout=10000)
            print("projector closed: console leader again · host clients =", health()["clients"])

            # a second console (another tab) must not steal the lead or open a second host link
            con2 = ctx.new_page(); con2.on("pageerror", lambda e: errs.append("console2: " + str(e)))
            con2.goto(f"http://127.0.0.1:{port}/#t={token}")
            con2.wait_for_function("window.T && T.link && T.link.peers.size >= 1", timeout=10000)
            time.sleep(2.0)
            leaders = [con.evaluate("T.link.isLeader()"), con2.evaluate("T.link.isLeader()")]
            print("two consoles: leaders =", leaders, "· host clients =", health()["clients"])
            if health()["clients"] != 1 or leaders != [True, False]:
                print("   DEBUG con:", con.evaluate("({mode:T.host.mode, conn:T.host.connected, id:T.link.id, since:T.link.since, peers:[...T.link.peers.entries()]})"))
                print("   DEBUG con2:", con2.evaluate("({mode:T.host.mode, conn:T.host.connected, id:T.link.id, since:T.link.since, peers:[...T.link.peers.entries()], log:T.log.buf.filter(e=>e.src==='link'||e.src==='host').map(e=>e.msg)})"))
                print("   DEBUG host windows:", health().get("windows"))
                time.sleep(3)
                print("   DEBUG 3 s later: host clients =", health()["clients"], health().get("windows"))
            assert leaders == [True, False] and health()["clients"] == 1, (leaders, health()["clients"])
            con.close()
            con2.wait_for_function("T.link.isLeader() && T.host.connected", timeout=10000)
            print("first console closed: the second takes over")
            b.close()
            assert not errs, errs
        print("DUAL-WINDOW OK")
    finally:
        proc.terminate()
        proc.communicate(timeout=5)


if __name__ == "__main__":
    main()
