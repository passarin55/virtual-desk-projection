/* ==========================================================================
   TABULA-Ω · projector mode + boot + frame loop
   ========================================================================== */
'use strict';

T.proj = {
  editing: false, sel: 0, drag: null, hudTimer: 0,
  enter(user) {
    document.body.classList.add('projecting'); T.render.projecting = true;
    if (!T.warp.canvas) T.warp.init(document.getElementById('projOut'));
    this.hud(true);
    if (user) this.fullscreen();
  },
  exit() {
    if (T.isProjector) { if (this.hudShown()) this.hud(false); else this.hud(true, 10000); return; }   // the projector window stays a projector: Esc toggles help
    document.body.classList.remove('projecting', 'edit'); T.render.projecting = false; this.editing = false;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  },
  async fullscreen() {
    const el = document.documentElement;
    try {
      if ('getScreenDetails' in window) {
        const sd = await window.getScreenDetails();
        const target = sd.screens.find((s) => !s.isPrimary) || sd.currentScreen;
        await el.requestFullscreen({ screen: target, navigationUI: 'hide' });
        T.log.info('proj', `fullscreen on ${target.label || 'screen'} ${target.width}×${target.height}`);
        return;
      }
      await el.requestFullscreen({ navigationUI: 'hide' });
    } catch (e) {
      try { await el.requestFullscreen(); } catch (e2) { T.log.warn('proj', 'fullscreen refused (' + e2.message + ') — drag this window onto the projector and press F'); }
    }
  },
  /* The help card is projected onto the desk itself, so it must never sit on the controls: it shows for a few seconds
     when projection starts (and while editing corner pins), in the spot that covers the fewest desk targets, and
     otherwise only when asked for (H or ?). Moving the mouse does not bring it back. */
  hud(show, ms = 5000) {
    const h = document.getElementById('projHud');
    h.innerHTML = `<b>TABULA-Ω projector</b> · ${T.warp.ok ? 'WebGL2 warp' : '2D warp'} · ${T.cfg.output.res.join('×')}<br>F fullscreen · G mm grid · C corner pins (drag, 1–4 + arrows) · H or ? this help · Esc ${T.isProjector ? 'help' : 'back to console'}<br>
      <button type="button" data-a="fs">Fullscreen on projector</button><button type="button" data-a="grid">Grid</button><button type="button" data-a="edit">${this.editing ? 'Done' : 'Corner pins'}</button>${T.isProjector ? '' : '<button type="button" data-a="exit">Back to console</button>'}<button type="button" data-a="hide">Hide</button>`;
    h.classList.toggle('show', !!show);
    clearTimeout(this.hudTimer);
    if (show) { this.placeHud(h); if (!this.editing && ms) this.hudTimer = setTimeout(() => h.classList.remove('show'), ms); }
  },
  hudShown() { return document.getElementById('projHud').classList.contains('show'); },
  /* window-pixel boxes of every tappable desk target, mapped through the corner pins */
  controlBoxes() {
    const Hc = T.cornerH(); if (!Hc) return [];
    const o = T.cfg.output, W = T.cfg.desk.w, H = T.cfg.desk.h, vw = innerWidth, vh = innerHeight;
    const toWin = (x, y) => { let s = x / W, t = y / H; if (o.flipX) s = 1 - s; if (o.flipY) t = 1 - t; const [u, v] = T.m3.apply(Hc, s, t); return [u * vw, v * vh]; };
    return T.engine.targets().map((r) => {
      const p = [toWin(r.x, r.y), toWin(r.x + r.w, r.y), toWin(r.x, r.y + r.h), toWin(r.x + r.w, r.y + r.h)], xs = p.map((q) => q[0]), ys = p.map((q) => q[1]);
      return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
    });
  },
  placeHud(h) {
    const vw = innerWidth, vh = innerHeight, m = 12, bw = h.offsetWidth, bh = h.offsetHeight, boxes = this.controlBoxes();
    // preference order on ties: bottom centre (where the keyboard sits), bottom corners, top, centre
    const cand = [[(vw - bw) / 2, vh - bh - m], [m, vh - bh - m], [vw - bw - m, vh - bh - m], [(vw - bw) / 2, m], [vw - bw - m, m], [m, m], [(vw - bw) / 2, (vh - bh) / 2]];
    let best = cand[0], bestCost = Infinity;
    for (const [x, y] of cand) {
      let cost = 0;
      for (const b of boxes) cost += Math.max(0, Math.min(x + bw, b.x + b.w) - Math.max(x, b.x)) * Math.max(0, Math.min(y + bh, b.y + b.h) - Math.max(y, b.y));
      if (this.editing) for (const p of T.cfg.output.corners) { const cx = p[0] * vw, cy = p[1] * vh; if (cx > x - 48 && cx < x + bw + 48 && cy > y - 48 && cy < y + bh + 48) cost += 1e9; }   // never over a corner pin being edited
      if (cost < bestCost) { bestCost = cost; best = [x, y]; }
    }
    h.style.left = Math.round(Math.max(m, best[0])) + 'px'; h.style.top = Math.round(Math.max(m, best[1])) + 'px';
  },
  toggleEdit() { this.editing = !this.editing; document.body.classList.toggle('edit', this.editing); this.hud(true, this.editing ? 0 : 2500); },
  bind() {
    const cv = document.getElementById('projOut'), hud = document.getElementById('projHud');
    hud.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.a === 'fs') this.fullscreen(); if (b.dataset.a === 'grid') T.call('patchCfg', { patch: { output: { grid: !T.cfg.output.grid } } });
      if (b.dataset.a === 'edit') this.toggleEdit(); if (b.dataset.a === 'exit') this.exit(); if (b.dataset.a === 'hide') this.hud(false);
    });
    const norm = (e) => [e.clientX / cv.clientWidth, e.clientY / cv.clientHeight];
    const toDesk = (cx, cy) => { const [x, y] = T.outToDesk(cx / cv.clientWidth, cy / cv.clientHeight); return x == null || x < -20 || y < -20 || x > T.cfg.desk.w + 20 || y > T.cfg.desk.h + 20 ? [null, null] : [x, y]; };
    this.sim = new T.SimPointer(cv, toDesk, (phase, id, x, y, extra) => { if (!this.editing) T.input.ev('sim', id, phase, x, y, extra); });
    cv.addEventListener('pointerdown', (e) => {
      if (!this.editing) return; const [u, v] = norm(e); let best = -1, bd = 0.05;
      T.cfg.output.corners.forEach((p, i) => { const d = Math.hypot(p[0] - u, p[1] - v); if (d < bd) { bd = d; best = i; } });
      if (best >= 0) { this.sel = best; this.drag = best; }
    }, true);
    cv.addEventListener('pointermove', (e) => { if (!this.editing || this.drag == null) return; const [u, v] = norm(e); const c = T.cfg.output.corners.map((p) => p.slice()); c[this.drag] = [u, v]; T.cfg.output.corners = c; T.setCfgDirty(); }, true);
    cv.addEventListener('pointerup', () => { this.drag = null; }, true);
    window.addEventListener('resize', () => { if (T.render.projecting && this.hudShown()) this.placeHud(document.getElementById('projHud')); });
    window.addEventListener('keydown', (e) => {
      if (!T.render.projecting) return;
      const k = e.key.toLowerCase();
      if (k === 'f') this.fullscreen();
      else if (k === 'g') T.call('patchCfg', { patch: { output: { grid: !T.cfg.output.grid } } });
      else if (k === 'c') this.toggleEdit();
      else if (k === 'h' || e.key === '?') { if (this.hudShown() && !this.editing) this.hud(false); else this.hud(true, 10000); }
      else if (k === 'escape') { if (this.editing) this.toggleEdit(); else this.exit(); }
      else if (/^[1-4]$/.test(k)) this.sel = +k - 1;
      else if (this.editing && e.key.startsWith('Arrow')) {
        e.preventDefault(); const st = e.shiftKey ? 10 : 1, [rw, rh] = T.cfg.output.res, d = { arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1] }[k];
        const c = T.cfg.output.corners.map((p) => p.slice()); c[this.sel] = [c[this.sel][0] + d[0] * st / rw, c[this.sel][1] + d[1] * st / rh]; T.cfg.output.corners = c; T.setCfgDirty();
      }
    });
  },
  drawOverlay() {
    const ov = document.getElementById('projOverlay'), w = ov.clientWidth, h = ov.clientHeight;
    if (ov.width !== w || ov.height !== h) { ov.width = w; ov.height = h; }
    const g = ov.getContext('2d'); g.clearRect(0, 0, w, h);
    if (!this.editing) return;
    const c = T.cfg.output.corners;
    g.strokeStyle = '#ffc861'; g.lineWidth = 2; g.beginPath(); c.forEach((p, i) => (i ? g.lineTo(p[0] * w, p[1] * h) : g.moveTo(p[0] * w, p[1] * h))); g.closePath(); g.stroke();
    c.forEach((p, i) => { g.fillStyle = i === this.sel ? '#ffc861' : '#7cf0ff'; g.beginPath(); g.arc(p[0] * w, p[1] * h, 14, 0, 7); g.fill(); g.fillStyle = '#000'; g.font = '700 15px sans-serif'; g.textAlign = 'center'; g.fillText(String(i + 1), p[0] * w, p[1] * h + 5); });
  },
};

T.boot = async function () {
  T.loadCfg();
  if (T.BOOT && T.BOOT.cfg && T.BOOT.cfg.v === T.cfg.v) T.deepMerge(T.cfg, T.BOOT.cfg);
  T.render.init();
  T.engine.init();
  T.link.init();
  T.ui.init();
  T.proj.bind();
  T.log.info('boot', `TABULA-Ω ${T.VERSION} · ${T.isProjector ? 'projector window' : 'console'} · desk ${T.cfg.desk.w}×${T.cfg.desk.h} mm · surface ${T.render.texW}×${T.render.texH}px`);
  if (T.isProjector) T.proj.enter(false);
  const wanted = () => (T.BOOT ? 'live' : T.cfg.host.mode || 'sim');
  T.bus.on('link:role', (lead) => { if (lead) T.host.start(wanted()); else { T.host.start('off'); T.air.stop(); } });
  setTimeout(() => { if (T.link.isLeader()) T.host.start(wanted()); }, 600);   // let other windows announce themselves first
  T.bus.on('cfg:changed', () => { const k = T.cfg.output.res.join('x') + ':' + T.cfg.desk.w + 'x' + T.cfg.desk.h; if (k !== T._resKey) { T._resKey = k; T.render.resize(); T.engine.layoutDirty = true; } if (T.midi.access && T.cfg.midi.outId && (!T.midi.out || T.midi.out.id !== T.cfg.midi.outId)) T.midi.pick(T.cfg.midi.outId); });
  T._resKey = T.cfg.output.res.join('x') + ':' + T.cfg.desk.w + 'x' + T.cfg.desk.h;
  try { await Promise.race([Promise.all(['600 12px "Barlow Semi Condensed"', '500 12px "Barlow Semi Condensed"', '400 12px "JetBrains Mono"', '400 12px "Michroma"'].map((f) => document.fonts.load(f))), T.sleep(1500)]); } catch (e) { /* offline: fallbacks */ }
  let last = performance.now(), lastDraw = 0;
  const loop = (now) => {
    requestAnimationFrame(loop);
    const dt = Math.min(0.1, Math.max(0, (now - last) / 1000)); last = now;
    try {
      let drew = false;
      if (T.link.isLeader()) {
        T.air.poll(now);
        T.engine.tick(dt, now);
        if (T.engine.isBusy(now) || now - lastDraw > 250) {
          T.engine.dirty = false; lastDraw = now; drew = true;
          T.engine.drawSurface(T.render.sctx, T.render.texW, T.render.texH, now);
          if (T.render.projecting) { T.warp.draw(T.render.surface); T.proj.drawOverlay(); }
        }
        T.link.tick(now);
      } else drew = T.link.pvFresh || T.ui.objDrag; 
      if (!T.render.projecting) { if (T.ui.tab === 'desk' && (drew || T.ui.objDrag)) { T.ui.drawDesk(); T.link.pvFresh = false; } else if (T.ui.tab === 'calib') T.ui.drawPin(now); }
    } catch (e) { if (!T._loopErr || now - T._loopErr > 2000) { T._loopErr = now; T.log.err('loop', e.message + (e.stack ? ' @ ' + e.stack.split('\n')[1] : '')); } }
  };
  requestAnimationFrame(loop);
  window.addEventListener('beforeunload', () => { if (T.host.armed) T.host.panic('page closed'); });
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', T.boot); else T.boot();
