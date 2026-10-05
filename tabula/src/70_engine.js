/* ==========================================================================
   TABULA-Ω · engine — workspaces, slot layout with object-aware relocation
   (Desktopography: "the burden of responsiveness falls to the digital
   elements"), contact dispatch, tools, surface rendering.
   ========================================================================== */
'use strict';

T.engine = {
  widgets: new Map(), rail: null, ws: 'DEV', auto: true, profile: null, tool: null,
  objects: [], simObjects: [], hostObjects: [], tokenState: new Map(), layoutDirty: true, lastLayout: 0, stats: { frames: 0, ft: [], fps: 0, t: 0 }, dirty: true, animating: false,
  init() {
    for (const k of Object.keys(T.W)) if (k !== 'rail') this.widgets.set(k, new T.W[k]());
    this.rail = new T.W.rail();
    const saved = T.cfg.ui.ws; this.auto = saved === 'AUTO' || !saved; this.ws = T.WORKSPACES[saved] ? saved : 'DEV';
    this.profile = T.PROFILES[0];
    T.bus.on('host:focus', (f) => this.onFocus(f));
    T.bus.on('panic', () => { T.input.releaseAll(); this.tool = null; });
  },
  get(kind) { return this.widgets.get(kind); },
  onFocus(f) {
    const p = T.matchProfile(f); const changed = p !== this.profile; this.profile = p;
    if (changed) { T.log.info('focus', `${f.app || f.exe} → palette “${p.name}”`); if (this.auto && p.ws && p.ws !== this.ws) this.setWorkspace(p.ws); }
  },
  setAuto(on) { this.auto = on; T.cfg.ui.ws = on ? 'AUTO' : this.ws; T.setCfgDirty(); if (on && this.profile && this.profile.ws) this.setWorkspace(this.profile.ws); },
  setWorkspace(name, manual) {
    if (!T.WORKSPACES[name]) return;
    if (manual && this.auto) this.auto = false;
    if (this.ws !== name) T.log.info('desk', 'workspace ' + name);
    this.ws = name; if (!this.auto) T.cfg.ui.ws = name; this.layoutDirty = true; T.setCfgDirty();
  },
  activateTool(name) {
    if (name === 'scan') { if (!this.slotOf('scan')) this.setWorkspace('PAPER'); return; }
    if (name === 'ink') { if (!this.slotOf('ink')) this.setWorkspace('MAKE'); return; }
    this.tool = name || null;
  },
  slotOf(kind) { const w = T.WORKSPACES[this.ws]; return Object.keys(w).find((s) => s !== 'label' && w[s] === kind) || null; },
  visible() { const out = []; for (const w of this.widgets.values()) if (w.active) out.push(w); return out; },
  setHostObjects(list) {
    const now = T.now(), map = T.cfg.tokens || {};
    for (const o of list) {
      if (o.kind !== 'token') continue;
      const m = map[String(o.id)]; if (m && m.tag) o.tag = m.tag;
      let st = this.tokenState.get(o.id);
      if (!st || now - st.seen > 1500) {                          // token placed → run its binding once
        st = { angle: o.angle, acc: 0, seen: now, since: now }; this.tokenState.set(o.id, st);
        if (m) { if (m.ws) this.setWorkspace(m.ws, true); if (m.a) T.actions.run(m.a); T.fx.callout(o.x, o.y, (m.l || 'token ' + o.id) + ' placed'); }
      }
      if (m && m.dial && o.angle != null) {                          // rotating a puck = a physical dial
        let d = o.angle - st.angle; if (d > 180) d -= 360; if (d < -180) d += 360; st.angle = o.angle; st.acc += d;
        while (st.acc >= 15) { st.acc -= 15; T.actions.run(m.dial.cw); }
        while (st.acc <= -15) { st.acc += 15; T.actions.run(m.dial.ccw); }
      }
      st.seen = now;
    }
    const sig = list.map((o) => `${o.kind}${o.id || ''}:${Math.round(o.x / 10)},${Math.round(o.y / 10)}`).join('|');
    this.hostObjects = list; if (sig !== this._objSig) { this._objSig = sig; this.layoutDirty = true; }
  },
  drawTokens(G, now) {
    const map = T.cfg.tokens || {};
    for (const o of this.hostObjects) {
      if (o.kind !== 'token') continue; const m = map[String(o.id)], r = Math.max(o.w || 30, o.h || 30) / 2 + 9;
      G.ring(o.x, o.y, r, T.alpha(T.PAL.violet, 0.8), 1); const a = (o.angle || 0) * Math.PI / 180;
      G.line(o.x + Math.cos(a) * r, o.y + Math.sin(a) * r, o.x + Math.cos(a) * (r + 5), o.y + Math.sin(a) * (r + 5), T.PAL.violet, 1.4);
      G.text(m ? m.l : 'token ' + o.id, o.x, o.y + r + 7, { sz: T.TYPE.min, al: 'center', col: T.PAL.violet });
    }
  },
  setSimObjects(list) { this.simObjects = list; this.layoutDirty = true; },
  handPolys() { return [...(T.input.hands || []), ...(T.air.hands || []), ...(T.input.hostHands || [])]; },

  /* ---------------- layout ---------------- */
  slotRect(slot) {
    const f = T.SLOTS[slot], W = T.cfg.desk.w, H = T.cfg.desk.h; let x = f[0] * W;
    if (T.cfg.desk.handed === 'left') x = W - x - f[2] * W;
    return { x, y: f[1] * H, w: f[2] * W, h: f[3] * H };
  },
  railRect() { const H = T.cfg.desk.h; return { x: 4, y: 3, w: T.cfg.desk.w - 8, h: Math.max(30, Math.min(40, 0.064 * H)) }; },
  kbRect() { const k = T.cfg.desk.kb, W = T.cfg.desk.w, H = T.cfg.desk.h; return k && k.on ? { x: k.x * W, y: k.y * H, w: k.w * W, h: k.h * H } : null; },
  obstacles() {
    const obs = [];
    const kb = this.kbRect(); if (kb) obs.push(kb);
    for (const o of [...this.simObjects, ...this.hostObjects]) obs.push(o.r ? { x: o.x - o.r, y: o.y - o.r, w: 2 * o.r, h: 2 * o.r } : { x: o.x - o.w / 2, y: o.y - o.h / 2, w: o.w, h: o.h });
    return obs;
  },
  layout() {
    const wsDef = T.WORKSPACES[this.ws], obs = this.obstacles(), W = T.cfg.desk.w, H = T.cfg.desk.h, rail = this.railRect();
    this.objects = [...this.simObjects, ...this.hostObjects];
    this.rail.place(rail, false);
    for (const w of this.widgets.values()) w.active = false;
    const placed = [];
    const order = ['C', 'R1', 'R2', 'R3', 'L1', 'L2', 'B'];
    for (const slot of order) {
      const kind = wsDef[slot]; if (!kind) continue;
      if (slot === 'B' && this.kbRect()) continue;
      const w = this.widgets.get(kind); if (!w) continue;
      const home = this.slotRect(slot); let best = home;
      const over = (r) => obs.reduce((s, o) => s + T.geom.rectOverlap(r, o), 0) / (r.w * r.h);
      if (over(home) > 0.1) {
        let bestCost = Infinity; best = null;
        for (const sc of [1, 0.85, 0.72]) {
          const rw = home.w * sc, rh = home.h * sc;
          for (let y = rail.y + rail.h + 3; y + rh <= H - 2; y += 8) for (let x = 2; x + rw <= W - 2; x += 8) {
            const r = { x, y, w: rw, h: rh };
            if (placed.some((p) => T.geom.rectOverlap(r, p) > 1)) continue;
            const ov = over(r), cost = ov * 5000 + Math.hypot(x + rw / 2 - (home.x + home.w / 2), y + rh / 2 - (home.y + home.h / 2)) + (1 - sc) * 400;
            if (cost < bestCost) { bestCost = cost; best = r; }
          }
          if (best && over(best) < 0.02) break;
        }
        best = best || home;
        if (best !== home && !w._moved) { T.log.info('layout', `${kind} moved to make room for a physical object`); w._moved = true; }
      } else w._moved = false;
      placed.push(best); w.place(best); w.active = true; w.slot = slot;
    }
    for (const w of this.widgets.values()) if (!w.active) w.vis = 0;
    this.layoutDirty = false; this.lastLayout = T.now();
  },

  /* ---------------- contacts ---------------- */
  contactsOf(w) { const out = []; for (const c of T.input.contacts.values()) if (c.widget === w) out.push(c); return out; },
  contactDown(c) {
    if (T.calib.acc.active) { T.calib.acc.tap(c); c.widget = 'calib'; return; }
    if (this.rail.hit(c.x, c.y)) { c.widget = this.rail; this.rail.down(c); return; }
    const vis = this.visible();
    for (const w of vis) if (w.hit(c.x, c.y)) {
      if (this.tool === 'measure' && w.kind !== 'ruler') break;
      if (w.down(c)) { c.widget = w; return; }
    }
    if (this.tool && T.tools[this.tool]) { c.widget = 'tool'; T.tools[this.tool].down(c); return; }
    c.widget = null; T.fx.ripple(c.x, c.y, T.PAL.dim, 6);
  },
  contactMove(c) { if (c.widget && c.widget.move) c.widget.move(c); else if (c.widget === 'tool' && T.tools[this.tool] && T.tools[this.tool].move) T.tools[this.tool].move(c); },
  contactUp(c) { if (c.widget && c.widget.up) c.widget.up(c); },

  /* ---------------- per-frame ---------------- */
  tick(dt, now) {
    if (this.layoutDirty || now - this.lastLayout > 500) this.layout();
    this.rail.tick(dt, now);
    let anim = false;
    for (const w of this.widgets.values()) { if (w.active) { if (w.tickLayout(dt)) anim = true; w.tick(dt, now); } else if (w.kind === 'timer' || w.kind === 'portal') w.tick(dt, now); }
    this.animating = anim;
    // sim hand silhouettes follow the sim pointer (console demo of occlusion-aware placement + light masking)
    T.input.hands = [];
    if (T.cfg.input.simHand) {
      const pts = [...T.input.contacts.values(), ...T.input.hovers.values()].filter((c) => c.src === 'sim' && !String(c.id).startsWith('pin') && !String(c.id).startsWith('tw'));
      if (pts.length) T.input.hands = [T.input.simHandPoly(pts[0].x, pts[0].y, T.cfg.desk.handed)];
    }
    const st = this.stats; st.frames++; st.ft.push(dt * 1000); if (st.ft.length > 120) st.ft.shift();
    if (now - st.t > 1000) { st.fps = st.frames; st.frames = 0; st.t = now; }
  },
  /* adaptive pacing: full rate while anything moves, ~4 fps when the desk is still */
  isBusy(now) {
    const d = this.get('dials'), sc = this.get('scan');
    return this.dirty || this.animating || T.input.contacts.size > 0 || T.input.hovers.size > 0 || T.fx.ripples.length > 0 || T.fx.callouts.length > 0 ||
      !!T.calib.pattern || !!T.calib.flashRect || T.calib.acc.active || !!T.calib.hostTarget || T.air.on || (d && d.jogSpin) || (sc && sc.active && (sc.isFlashing(now) || sc.busy)) || (this.rail.holdArm != null) || (this.rail.holdEsc != null);
  },
  frameP95() { const a = this.stats.ft.slice().sort((x, y) => x - y); return a.length ? a[Math.floor(a.length * 0.95) - 1] || a[a.length - 1] : 0; },

  /* ---------------- drawing into the surface canvas (desk mm) ---------------- */
  drawSurface(ctx, texW, texH, now, opt = {}) {
    const W = T.cfg.desk.w, s = texW / W, G = T.gfx;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, texW, texH);
    if (T.calib.pattern) { T.gray.draw(ctx, T.calib.pattern.plan, T.calib.pattern.pat); return; }
    if (T.calib.flash) { ctx.fillStyle = T.calib.flash; ctx.fillRect(0, 0, texW, texH); return; }
    G.begin(ctx, s);
    if (T.cfg.output.grid || T.calib.showGrid) this.drawGrid(G);
    const kb = this.kbRect(); if (kb && opt.preview) { ctx.strokeStyle = 'rgba(255,255,255,0.08)'; ctx.setLineDash([3, 3]); ctx.lineWidth = 0.6; ctx.strokeRect(kb.x, kb.y, kb.w, kb.h); ctx.setLineDash([]); }
    this.rail.draw(G, now);
    for (const w of this.visible()) { ctx.globalAlpha = w.vis; w.draw(G, now); ctx.globalAlpha = 1; }
    const tw = this.get('timer'); if (tw) tw.drawAnchors(G, now);
    T.tools.measure.draw(G, now);                       // annotations persist until CLEAR
    if (T.calib.acc.active) T.calib.acc.draw(G, now);
    T.calib.drawHostTarget(G, now);
    this.drawTokens(G, now);
    T.fx.draw(G, now);
    this.drawContacts(G, now);
    // light masking: dim projection falling on hands (comfort + legibility), black-out heads (glare guard)
    if (T.cfg.output.dimHands && !opt.preview) {
      ctx.save(); ctx.fillStyle = 'rgba(0,0,0,0.82)';
      for (const hp of this.handPolys()) { if (hp.length < 3) continue; ctx.beginPath(); hp.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]))); ctx.closePath(); ctx.fill(); }
      ctx.restore();
    }
    if (T.cfg.output.headGuard) for (const h of T.input.heads || []) G.disc(h.x, h.y, h.r, '#000');
    const sc = this.get('scan'); if (sc && sc.active && sc.isFlashing(now)) { const L = sc.layout(); ctx.fillStyle = '#fff'; ctx.fillRect(L.bay.x, L.bay.y, L.bay.w, L.bay.h); }
    if (T.calib.flashRect) { const r = T.calib.flashRect; ctx.fillStyle = '#fff'; ctx.fillRect(r.x, r.y, r.w, r.h); }
  },
  drawGrid(G) {
    const g = G.g, W = T.cfg.desk.w, H = T.cfg.desk.h;
    for (let x = 0; x <= W; x += 10) G.line(x, 0, x, H, x % 100 === 0 ? 'rgba(124,240,255,0.55)' : x % 50 === 0 ? 'rgba(124,240,255,0.28)' : 'rgba(124,240,255,0.1)', x % 100 === 0 ? 0.6 : 0.3);
    for (let y = 0; y <= H; y += 10) G.line(0, y, W, y, y % 100 === 0 ? 'rgba(124,240,255,0.55)' : y % 50 === 0 ? 'rgba(124,240,255,0.28)' : 'rgba(124,240,255,0.1)', y % 100 === 0 ? 0.6 : 0.3);
    for (let x = 100; x < W; x += 100) G.text(String(x), x + 1.5, H - 3, { sz: T.TYPE.min, col: T.PAL.beam, fam: 'mono' });
    for (let y = 100; y < H; y += 100) G.text(String(y), 1.5, y - 1.5, { sz: T.TYPE.min, col: T.PAL.beam, fam: 'mono' });
    g.strokeStyle = T.PAL.amber; g.lineWidth = 1; g.strokeRect(0.5, 0.5, W - 1, H - 1);
    for (const [x, y] of [[0, 0], [W, 0], [W, H], [0, H], [W / 2, H / 2]]) { G.ring(x, y, 6, T.PAL.amber, 0.8); G.line(x - 9, y, x + 9, y, T.PAL.amber, 0.6); G.line(x, y - 9, x, y + 9, T.PAL.amber, 0.6); }
    G.text(`${W} × ${H} mm — every line is 10 mm on the real desk`, W / 2, H / 2 - 12, { sz: T.TYPE.body, al: 'center', col: T.PAL.amber });
  },
  drawContacts(G, now) {
    for (const c of T.input.contacts.values()) {
      const [px, py] = T.input.predict(c), col = c.src === 'host' ? T.PAL.ir : c.src === 'air' ? T.PAL.lime : T.PAL.beam;
      G.ring(px, py, 7, col, 1.2); G.disc(px, py, 1.4, col);
      if (px !== c.x) G.ring(c.x, c.y, 5, T.alpha(col, 0.35), 0.6);
    }
    for (const h of T.input.hovers.values()) {
      const col = h.src === 'host' ? T.PAL.ir : h.src === 'air' ? T.PAL.lime : T.PAL.dim;
      G.g.setLineDash([1.6, 1.6]); G.ring(h.x, h.y, 6, col, 0.8); G.g.setLineDash([]);
      if (h.dwell) { const k = Math.min(1, h.dwell / T.cfg.input.dwellMs); G.g.strokeStyle = col; G.g.lineWidth = 1.4; G.g.beginPath(); G.g.arc(h.x, h.y, 8.5, -Math.PI / 2, -Math.PI / 2 + k * Math.PI * 2); G.g.stroke(); }
    }
  },
  /* every interactive target currently on the desk (for the ergonomics critic) */
  targets() {
    if (T.link && !T.link.isLeader() && this.remoteTargets) return this.remoteTargets;
    const out = [...this.rail.targets()]; for (const w of this.visible()) for (const t of w.targets()) out.push(Object.assign({ widget: w.kind }, t)); return out;
  },
};
