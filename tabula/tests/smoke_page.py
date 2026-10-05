#!/usr/bin/env python3
"""Headless smoke test of the TABULA-Ω page (no host): every tab renders, no JS errors,
widgets react to simulated touches, Gray-code SIM CAM calibration converges."""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "dist" / "tabula.html").as_uri()
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

def main():
    errors, logs = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(args=ARGS)
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        pg.on("console", lambda m: (errors if m.type == "error" else logs).append(f"{m.type}: {m.text}"))
        pg.goto(PAGE)
        pg.wait_for_function("window.T && T.engine && T.engine.stats.fps > 0", timeout=15000)
        time.sleep(1.5)
        st = pg.evaluate("({fps:T.engine.stats.fps, ws:T.engine.ws, host:T.host.mode, conn:T.host.connected, armed:T.host.armed, warp:T.warp.ok, leader:T.link.isLeader(), tex:[T.render.texW,T.render.texH], widgets:T.engine.visible().map(w=>w.kind)})")
        print("state:", json.dumps(st))
        pg.screenshot(path=str(OUT / "01_desk.png"))

        # --- touch the palette's first button through the real sim pointer path
        pal = pg.evaluate("(()=>{const w=T.engine.get('palette'); w.compute(); const c=w.cells[0]; return {x:c.r.x+c.r.w/2, y:c.r.y+c.r.h/2, label:c.item.l}})()")
        box = pg.locator("#deskView").bounding_box()
        W = pg.evaluate("T.cfg.desk.w"); H = pg.evaluate("T.cfg.desk.h")
        def at(x, y): return box["x"] + x / W * box["width"], box["y"] + y / H * box["height"]
        n0 = pg.evaluate("T.log.buf.length")
        px, py = at(pal["x"], pal["y"]); pg.mouse.click(px, py); time.sleep(0.4)
        acts = pg.evaluate(f"T.log.buf.slice({n0}).filter(e=>e.level==='act').map(e=>e.msg)")
        print("palette tap →", pal["label"], acts)
        assert acts, "palette tap produced no action"

        # --- real presses span frames: down, several redraws (cells/keys are rebuilt every frame), then up
        slow = pg.evaluate("""(async () => {
          const wait = (ms) => new Promise((r) => setTimeout(r, ms));
          const press = async (x, y, id) => { T.api.pointer({ id, phase: 'down', x, y }); await wait(380); T.api.pointer({ id, phase: 'up', x, y }); await wait(60); };
          const acts = (n0) => T.log.buf.slice(n0).filter((e) => e.level === 'act').map((e) => e.msg);
          const out = {};
          const pal = T.engine.get('palette'); pal.compute(); const pc = pal.cells[0];
          let n0 = T.log.buf.length; T.api.pointer({ id: 'p1', phase: 'down', x: pc.r.x + pc.r.w / 2, y: pc.r.y + pc.r.h / 2 }); await wait(380);
          out.pressedShown = T.engine.contactsOf(pal).some((c) => c.data.cell && pal.same(c.data.cell, pal.cells[0]));
          T.api.pointer({ id: 'p1', phase: 'up', x: pc.r.x + pc.r.w / 2, y: pc.r.y + pc.r.h / 2 }); await wait(60);
          out.palette = acts(n0);
          const deck = T.engine.get('deck'); deck.compute(); const dc = deck.cells.find((c) => c.item.id === 'snip') || deck.cells[1];
          n0 = T.log.buf.length; await press(dc.r.x + dc.r.w / 2, dc.r.y + dc.r.h / 2, 'd1'); out.deck = acts(n0);
          const keys = T.engine.get('keys'); keys.set = 'NAV'; const up = keys.layout().find((k) => k.id === 'key:up');
          n0 = T.log.buf.length; await press(up.x + up.w / 2, up.y + up.h / 2, 'k1'); out.keys = acts(n0);
          const shift = keys.layout().find((k) => k.id === 'mod:shift'); await press(shift.x + shift.w / 2, shift.y + shift.h / 2, 'k2');
          out.sticky = [...keys.mods];
          const num = keys.layout().find((k) => k.id === 'set:NUM'); await press(num.x + num.w / 2, num.y + num.h / 2, 'k3');
          out.set = keys.set;
          return out;
        })()""")
        esc = pg.evaluate("""(async () => {
          const wait = (ms) => new Promise((r) => setTimeout(r, ms));
          const acts = (n0) => T.log.buf.slice(n0).filter((e) => e.level === 'act').map((e) => e.msg);
          const rail = T.engine.rail; rail.layout(); const b = rail.btns.find((x) => x.id === 'esc');
          const x = b.x + b.w / 2, y = b.y + b.h / 2, out = {};
          let n0 = T.log.buf.length; T.api.pointer({ id: 'e1', phase: 'down', x, y }); await wait(120); T.api.pointer({ id: 'e1', phase: 'up', x, y }); await wait(80); out.tap = acts(n0);
          n0 = T.log.buf.length; T.api.pointer({ id: 'e2', phase: 'down', x, y }); await wait(900); T.api.pointer({ id: 'e2', phase: 'up', x, y }); await wait(80); out.hold = acts(n0);
          return out; })()""")
        print("rail ESC:", esc)
        assert esc["tap"] == ["key Esc"] and esc["hold"] == ["key Esc , Esc , Esc"], esc
        print("slow presses (frames between down/up):", slow)
        assert slow["palette"] and slow["deck"] and slow["keys"], slow
        assert slow["pressedShown"] and slow["sticky"] == ["shift"] and slow["set"] == "NUM", slow

        # --- trackpad two-finger scroll (Ctrl-drag = parallel twin fingers)
        tp = pg.evaluate("(()=>{const r=T.engine.get('trackpad').pad(); return {x:r.x+r.w/2, y:r.y+r.h/2}})()")
        sx, sy = at(tp["x"], tp["y"])
        pg.keyboard.down("Control"); pg.mouse.move(sx, sy); pg.mouse.down()
        for k in range(12): pg.mouse.move(sx, sy + k * 6)
        pg.mouse.up(); pg.keyboard.up("Control"); time.sleep(0.2)
        mode = pg.evaluate("T.engine.get('trackpad').flash && T.engine.get('trackpad').flash.label")
        print("trackpad gesture:", mode); assert mode == "SCROLL", mode

        # --- dial rotation emits detents
        n0 = pg.evaluate("T.log.buf.length")
        k = pg.evaluate("(()=>{const w=T.engine.get('dials'); if(!w.active){T.engine.setWorkspace('MAKE',true); T.engine.layout();} w.layout(); const j=w.knobs[0]; return {cx:j.cx, cy:j.cy, r:j.r}})()")
        time.sleep(0.6)
        k = pg.evaluate("(()=>{const w=T.engine.get('dials'); w.layout(); const j=w.knobs[0]; return {cx:j.cx, cy:j.cy, r:j.r}})()")
        import math
        pts = [at(k["cx"] + math.cos(a) * k["r"] * 0.8, k["cy"] + math.sin(a) * k["r"] * 0.8) for a in [i * 0.2 for i in range(0, 20)]]
        pg.mouse.move(*pts[0]); pg.mouse.down()
        for q in pts[1:]: pg.mouse.move(*q)
        pg.mouse.up(); time.sleep(0.3)
        dial_acts = pg.evaluate(f"T.log.buf.slice({n0}).filter(e=>e.level==='act').length")
        print("dial detents logged:", dial_acts); assert dial_acts >= 5
        ang = pg.evaluate("T.engine.get('dials').ang[0]")
        print("knob angle kept across frames:", round(ang, 2)); assert abs(ang) > 0.5, ang
        pg.screenshot(path=str(OUT / "02_make.png"))

        # --- object relocation (Desktopography): drop a notebook on the palette
        pg.evaluate("T.engine.setWorkspace('DEV',true)")
        r0 = pg.evaluate("(()=>{T.engine.layout(); const r=T.engine.get('palette').tgt; return r})()")
        pg.evaluate(f"T.api.simObjects({{list:[{{id:'nb',kind:'notebook',x:{r0['x']+r0['w']/2},y:{r0['y']+r0['h']/2},w:148,h:210}}]}}); T.engine.layout()")
        r1 = pg.evaluate("T.engine.get('palette').tgt")
        print("palette moved:", r0, "→", r1); assert abs(r1["x"] - r0["x"]) + abs(r1["y"] - r0["y"]) > 20
        time.sleep(0.8); pg.screenshot(path=str(OUT / "03_relocate.png"))
        pg.evaluate("T.api.simObjects({list:[]})")

        # --- Gray-code SIM CAM
        res = pg.evaluate("T.api.gray({src:'sim', step:16}).then(r=>({ok:r.ok, cells:r.cells, inliers:r.inliers, rms:r.rms, rmsMm:r.rmsMm, truth:r.truthMm, n:r.plan&&r.plan.n, err:r.err}))")
        print("gray-code:", res); assert res["ok"] and res["truth"] < 2.0, res

        # --- every tab
        for tab in ["scheme", "calib", "funcs", "tribunal", "dossier", "link"]:
            pg.click(f"nav.tabs button[data-tab={tab}]"); time.sleep(0.5)
            pg.screenshot(path=str(OUT / f"tab_{tab}.png"), full_page=False)
        trib = pg.evaluate("T.tribunal.run().map(c=>c.name+':'+c.v)")
        print("tribunal:", trib)

        # --- projector mode (WebGL warp) renders something
        pg.click("nav.tabs button[data-tab=desk]")
        pg.evaluate("T.proj.enter(false)"); time.sleep(0.8)
        lit = pg.evaluate("(()=>{const c=document.getElementById('projOut'); const g=c.getContext('webgl2'); if(!g) return -1; const px=new Uint8Array(4*64*64); g.readPixels(c.width/2-32,c.height/2-32,64,64,g.RGBA,g.UNSIGNED_BYTE,px); let s=0; for(let i=0;i<px.length;i+=4) s+=px[i]+px[i+1]+px[i+2]; return s})()")
        print("warp ok:", pg.evaluate("T.warp.ok"), "centre light sum:", lit)
        pg.screenshot(path=str(OUT / "04_projector.png"))
        pg.evaluate("T.proj.exit()")
        b.close()
    errs = [e for e in errors if "fonts.g" not in e and "net::ERR" not in e]
    print("console errors:", len(errs)); [print("  ", e) for e in errs[:20]]
    warn = [l for l in logs if l.startswith("warning")]
    print("warnings:", len(warn)); [print("  ", w) for w in warn[:10]]
    assert not errs, "JS errors"
    print("SMOKE OK")

if __name__ == "__main__":
    main()
