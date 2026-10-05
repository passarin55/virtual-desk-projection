/* ==========================================================================
   TABULA-Ω · widgets (A): base class, rail, context palette, macro deck,
   trackpad, dials + jog wheel.
   ========================================================================== */
'use strict';

T.W = {};
T.Widget = class {
  constructor(kind, title, hue = T.PAL.beam) { this.kind = kind; this.title = title; this.hue = hue; this.rect = { x: 0, y: 0, w: 10, h: 10 }; this.tgt = null; this.placed = false; this.vis = 0; this.active = true; }
  place(r, animate = true) { this.tgt = Object.assign({}, r); if (!this.placed || !animate) { this.rect = Object.assign({}, r); this.placed = true; } }
  tickLayout(dt) {
    if (!this.tgt) return false; const k = 1 - Math.exp(-dt * 11), r = this.rect, t = this.tgt; let moving = this.vis < 1;
    for (const p of ['x', 'y', 'w', 'h']) { const d = t[p] - r[p]; if (Math.abs(d) >= 0.05) moving = true; r[p] += d * (Math.abs(d) < 0.05 ? 1 : k); }
    this.vis = Math.min(1, this.vis + dt * 4);
    return moving;
  }
  get body() { const r = this.rect; return { x: r.x + 3, y: r.y + 11, w: r.w - 6, h: r.h - 14 }; }
  hit(x, y) { const r = this.rect; return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }
  down() { return false; } move() {} up() {} hover() {} tick() {}
  draw(G) { G.frame(this.rect, this.title, { hue: this.hue }); }
  targets() { return []; }
  /* long-press helper for contacts that have not moved */
  held(c, ms = 550, tol = 4) { return !c.data.lp && c.maxD < tol && T.now() - c.t0 > ms; }
};

/* ============================ RAIL ============================ */
T.W.rail = class extends T.Widget {
  constructor() { super('rail', null); this.btns = []; this.holdArm = null; this.holdEsc = null; }
  layout() {
    const r = this.rect, h = r.h - 8, y = r.y + 4, B = [];
    let x = r.x + 4;
    for (const name of [...Object.keys(T.WORKSPACES), 'AUTO']) { B.push({ id: 'ws:' + name, x, y, w: 25, h, label: name }); x += 27; }
    const focusX = x + 3;
    let rx = r.x + r.w - 4;
    const put = (id, w, label) => { rx -= w; B.push({ id, x: rx, y, w, h, label }); rx -= 2.5; };
    put('panic', 27, 'PANIC'); put('media:next', 18, '⏭'); put('media:playpause', 18, '⏯'); put('media:prev', 18, '⏮');
    put('clock', 40, ''); put('telemetry', 58, ''); put('arm', 36, '');
    put('esc', 30, 'ESC');                                      // always here, in every workspace: backs out of menus, palettes, dialogs
    B.push({ id: 'focus', x: focusX, y, w: Math.max(40, rx - focusX - 3), h, label: '' });
    this.btns = B;
  }
  down(c) {
    const b = this.btns.find((b) => c.x >= b.x && c.x <= b.x + b.w && c.y >= b.y && c.y <= b.y + b.h);
    if (!b) return true;
    c.data.btn = b;
    // holds run on timers, not on frames: a slow or stalled frame loop must not stretch or swallow them
    if (b.id === 'arm' && !T.host.armed) { this.holdArm = { c, t0: T.now() }; this.holdArm.timer = setTimeout(() => this.armHeld(c), 2000); }
    if (b.id === 'esc') { this.holdEsc = { c, t0: T.now() }; this.holdEsc.timer = setTimeout(() => this.escHeld(c), 600); }
    return true;
  }
  up(c) {
    const b = c.data.btn; if (!b) return;
    if (this.holdArm && this.holdArm.c === c) { clearTimeout(this.holdArm.timer); this.holdArm = null; }
    if (this.holdEsc && this.holdEsc.c === c) { clearTimeout(this.holdEsc.timer); this.holdEsc = null; }
    const inside = c.x >= b.x - 3 && c.x <= b.x + b.w + 3 && c.y >= b.y - 3 && c.y <= b.y + b.h + 3;
    if (!inside || c.data.armed) return;
    T.fx.ripple(c.x, c.y, b.id === 'panic' ? T.PAL.red : T.PAL.beam);
    if (b.id.startsWith('ws:')) { const n = b.id.slice(3); if (n === 'AUTO') T.engine.setAuto(!T.engine.auto); else T.engine.setWorkspace(n, true); }
    else if (b.id.startsWith('media:')) T.actions.run({ do: 'media', op: b.id.slice(6) });
    else if (b.id === 'panic') T.host.panic('desk PANIC button');
    else if (b.id === 'esc') T.actions.run({ do: 'key', c: 'esc' });                     // one level back: menu, sub-menu, palette, find bar, dialog
    else if (b.id === 'arm') { if (T.host.armed) T.host.arm(false); else T.fx.callout(c.x, c.y, T.host.connected ? 'Hold 2 s to arm (TRIBUNAL gate must be open)' : 'No host connected', { col: T.PAL.amber }); }
    else if (b.id === 'focus' && T.host.mode === 'sim' && T.host.link) { T.host.link.setFocus(T.host.link.focusIdx + 1); }
  }
  escHeld(c) {                                                  // hold ESC: back out of nested menus in one go
    if (!this.holdEsc || this.holdEsc.c !== c || c.cancelled || c.maxD > 8) return;
    this.holdEsc = null; c.data.armed = true;                    // the release then sends nothing more
    T.actions.run({ do: 'key', c: ['esc', 'esc', 'esc'] });
    T.fx.callout(c.x, c.y, 'Esc ×3 — closed nested menus', { col: T.PAL.lime }); T.engine.dirty = true;
  }
  armHeld(c) {
    if (!this.holdArm || this.holdArm.c !== c || c.cancelled || c.maxD > 8) return;
    this.holdArm = null; c.data.armed = true;
    const gate = T.tribunal.gate();
    if (!gate.open) { T.fx.callout(c.x, c.y, 'Gate closed: ' + gate.why, { col: T.PAL.red, ttl: 4000 }); return; }
    T.host.arm(true, gate.report).then((r) => { if (!r.ok) T.fx.callout(c.x, c.y, 'Host refused: ' + (r.err || '?'), { col: T.PAL.red }); });
  }
  tick() {}
  draw(G, now) {
    this.layout();
    const g = G.g, r = this.rect;
    G.line(r.x, r.y + r.h, r.x + r.w, r.y + r.h, T.PAL.faint, 0.6);
    for (const b of this.btns) {
      if (b.id.startsWith('ws:')) {
        const n = b.id.slice(3), on = n === 'AUTO' ? T.engine.auto : T.engine.ws === n;
        G.button(b, b.label, { on, sz: T.TYPE.min, hue: n === 'AUTO' ? T.PAL.lime : T.PAL.beam });
      } else if (b.id === 'focus') {
        const f = T.host.focus, p = T.engine.profile;
        G.text(p ? p.glyph : '◇', b.x + 2, b.y + b.h / 2 + 3.5, { sz: T.TYPE.title, w: 700, col: T.PAL.beam, fam: 'mono' });
        G.fit(f ? (f.app || f.exe) : 'no focus data', b.x + 16, b.y + 11, b.w - 18, { sz: T.TYPE.body, w: 700 });
        G.fit(f ? f.title || '' : (T.host.connected ? 'waiting for focus…' : 'host offline'), b.x + 16, b.y + b.h - 3, b.w - 18, { sz: T.TYPE.min, col: T.PAL.dim });
      } else if (b.id === 'arm') {
        const sim = T.host.mode === 'sim', armed = T.host.armed, col = !T.host.connected ? T.PAL.dim : armed ? (sim ? T.PAL.beam : T.PAL.red) : T.PAL.green;
        G.rr(b.x, b.y, b.w, b.h, b.h / 2); g.fillStyle = T.alpha(col, armed ? 0.25 : 0.08); g.fill(); g.strokeStyle = col; g.lineWidth = 1.1; g.stroke();
        if (this.holdArm) { const k = Math.min(1, (now - this.holdArm.t0) / 2000); g.strokeStyle = T.PAL.red; g.lineWidth = 2; g.beginPath(); g.arc(b.x + b.w / 2, b.y + b.h / 2, b.h / 2 + 2, -Math.PI / 2, -Math.PI / 2 + k * Math.PI * 2); g.stroke(); }
        G.text(!T.host.connected ? 'OFFLINE' : armed ? (sim ? 'SIM·LIVE' : 'ARMED') : 'SAFE', b.x + b.w / 2, b.y + b.h / 2 + 2.2, { sz: T.TYPE.min, w: 700, al: 'center', col });
      } else if (b.id === 'clock') {
        const d = new Date();
        G.text(d.toTimeString().slice(0, 5), b.x + b.w / 2, b.y + 12.5, { sz: T.TYPE.title + 1, w: 600, al: 'center', fam: 'mono' });
        G.text(d.toDateString().slice(0, 10).toUpperCase(), b.x + b.w / 2, b.y + b.h - 2.5, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
      } else if (b.id === 'telemetry') {
        const tm = T.host.telemetry, cpu = tm ? tm.cpu : 0, gpu = tm && tm.gpus && tm.gpus.length ? Math.max(...tm.gpus.map((x) => x.util || 0)) : 0;
        [[`CPU ${Math.round(cpu)}%`, cpu, T.PAL.beam], [`GPU ${Math.round(gpu)}%`, gpu, T.PAL.ir]].forEach(([l, v, col], i) => {
          const yy = b.y + 3 + i * (b.h / 2);
          G.text(l, b.x, yy + 7, { sz: T.TYPE.min, col: T.PAL.dim, fam: 'ui' });
          g.fillStyle = T.alpha(col, 0.18); g.fillRect(b.x + 27, yy + 3, b.w - 28, 4.5); g.fillStyle = col; g.fillRect(b.x + 27, yy + 3, (b.w - 28) * T.clamp(v / 100, 0, 1), 4.5);
        });
      } else if (b.id === 'panic') {
        G.button(b, 'PANIC', { hue: T.PAL.red, sz: T.TYPE.min });
      } else if (b.id === 'esc') {
        G.button(b, 'ESC', { hue: T.PAL.lime, sz: T.TYPE.body, hint: 'hold ×3' });
        if (this.holdEsc) { const k = Math.min(1, (now - this.holdEsc.t0) / 600); g.strokeStyle = T.PAL.lime; g.lineWidth = 1.6; g.beginPath(); g.moveTo(b.x, b.y + b.h + 1.2); g.lineTo(b.x + b.w * k, b.y + b.h + 1.2); g.stroke(); }
      } else G.button(b, b.label, { hue: T.PAL.amber, sz: T.TYPE.body });
    }
  }
  targets() { this.layout(); return this.btns.filter((b) => b.id !== 'clock' && b.id !== 'telemetry').map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.h, label: 'rail ' + b.id })); }
};

/* ============================ BUTTON WALL (shared) ============================ */
T.ButtonWall = class extends T.Widget {
  constructor(kind, title, hue) { super(kind, title, hue); this.page = 0; this.cells = []; this.pages = 1; this.running = new Set(); }
  items() { return []; }
  header(G) { G.frame(this.rect, this.title, { hue: this.hue }); }
  gridArea() { const b = this.body; return { x: b.x, y: b.y + 1, w: b.w, h: b.h - 6 }; }
  compute() {
    const it = this.items(), area = this.gridArea();
    const gd = T.grid(area, it.length, { minW: this.minW || 42, minH: this.minH || 19 });
    this.pages = Math.max(1, Math.ceil(it.length / gd.perPage)); this.page = T.clamp(this.page, 0, this.pages - 1);
    const start = this.page * gd.perPage;
    this.cells = it.slice(start, start + gd.perPage).map((item, i) => ({ item, r: gd.cell(i), idx: start + i }));
    return gd;
  }
  cellAt(x, y) { return this.cells.find((c) => x >= c.r.x && x <= c.r.x + c.r.w && y >= c.r.y && y <= c.r.y + c.r.h); }
  same(a, b) { return !!a && !!b && a.idx === b.idx && a.item.l === b.item.l; }   // cells are rebuilt every frame: compare by slot + label, never by object
  down(c) { this.compute(); c.data.cell = this.cellAt(c.x, c.y) || null; return true; }
  move(c) {
    if (c.data.cell && !this.same(this.cellAt(c.x, c.y), c.data.cell)) c.data.cell = null;   // slid off the key: cancel
    if (!c.data.swiped && Math.abs(c.x - c.x0) > 40 && Math.abs(c.y - c.y0) < 20 && this.pages > 1) { c.data.swiped = true; c.data.cell = null; this.page = (this.page + (c.x < c.x0 ? 1 : -1) + this.pages) % this.pages; }
  }
  up(c) {
    const cell = c.data.cell; if (!cell || c.data.lp || c.cancelled) return;
    const now = this.cellAt(c.x, c.y); if (!this.same(now, cell)) return;
    T.fx.ripple(c.x, c.y, T.hue(now.item.g));
    this.fire(now.item, c);
  }
  tick(dt, now) {
    for (const c of T.engine.contactsOf(this)) if (c.data.cell && this.held(c)) { c.data.lp = true; T.fx.callout(c.x, c.y, this.explain(c.data.cell.item), { ttl: 3600 }); }
  }
  explain(item) { return item.l + ' → ' + T.actions.describe(item.a || { do: 'seq', steps: item.steps || [] }); }
  fire(item) { T.actions.run(item.a); }
  hintFor(item) { return item.a && item.a.do === 'key' ? T.chord.pretty(item.a.c) : ''; }
  draw(G, now) {
    this.header(G); this.compute();
    const pressed = T.engine.contactsOf(this).map((c) => c.data.cell).filter(Boolean);
    for (const cell of this.cells) G.button(cell.r, cell.item.l, { hue: T.hue(cell.item.g), pressed: pressed.some((p) => this.same(p, cell)), on: cell.item.on || this.running.has(cell.item), hint: this.hintFor(cell.item) });
    if (this.pages > 1) {
      const b = this.body, y = b.y + b.h - 1.5;
      for (let i = 0; i < this.pages; i++) G.disc(b.x + b.w / 2 + (i - (this.pages - 1) / 2) * 6, y, i === this.page ? 1.6 : 1.0, i === this.page ? this.hue : T.PAL.dim);
    }
  }
  targets() { this.compute(); return this.cells.map((c) => Object.assign({ label: this.kind + ' ' + c.item.l }, c.r)); }
};

/* ============================ PALETTE (follows the focused app) ============================ */
T.W.palette = class extends T.ButtonWall {
  constructor() { super('palette', 'PALETTE', T.PAL.beam); this.pinned = null; }
  get profile() { return this.pinned || T.engine.profile || T.PROFILES[0]; }
  items() {
    const p = this.profile;
    let b = p.buttons.filter((it) => !it.a || it.a.do !== 'key' || T.chord.pick(it.a.c) != null);
    if (p.dynamic === 'obs-scenes' && T.host.obs && T.host.obs.scenes) b = b.concat(T.host.obs.scenes.map((s) => ({ l: '▶ ' + s, g: 'scene', on: s === T.host.obs.current, a: { do: 'obs', req: 'SetCurrentProgramScene', data: { sceneName: s } } })));
    return b;
  }
  gridArea() { const b = this.body; return { x: b.x, y: b.y + 10, w: b.w, h: b.h - 15 }; }
  header(G) {
    const r = this.rect, p = this.profile;
    G.frame(r, null, { hue: this.hue });
    G.rr(r.x + 3, r.y + 3, 12, 12, 2); G.g.strokeStyle = this.hue; G.g.lineWidth = 0.8; G.g.stroke();
    G.fit(p.glyph, r.x + 9, r.y + 11.3, 11, { sz: T.TYPE.small, w: 700, al: 'center', col: this.hue, fam: 'mono' });
    G.fit(p.name.toUpperCase(), r.x + 18, r.y + 11.8, r.w - 60, { sz: T.TYPE.title, w: 700 });
    G.text(this.pinned ? 'PINNED ●' : 'FOLLOWS FOCUS', r.x + r.w - 4, r.y + 11, { sz: T.TYPE.min, al: 'right', col: this.pinned ? T.PAL.amber : T.PAL.dim });
  }
  down(c) { if (c.y < this.rect.y + 17) { c.data.head = true; return true; } return super.down(c); }
  up(c) {
    if (c.data.head) { if (c.maxD < 5) { this.pinned = this.pinned ? null : this.profile; T.fx.callout(c.x, c.y, this.pinned ? 'Palette pinned to ' + this.pinned.name : 'Palette follows the focused app'); } return; }
    super.up(c);
  }
};

/* ============================ DECK (macros) ============================ */
T.W.deck = class extends T.ButtonWall {
  constructor() { super('deck', 'MACRO DECK', T.PAL.lime); this.minW = 40; }
  items() { return T.cfg.macros; }
  hintFor(m) { return m.steps.length > 1 ? m.steps.length + ' steps' : T.actions.describe(m.steps[0]).slice(0, 22); }
  explain(m) { return m.l + ': ' + m.steps.map((s) => T.actions.describe(s)).join(' → '); }
  fire(m) { this.running.add(m); T.actions.run({ do: 'seq', steps: m.steps }).finally(() => this.running.delete(m)); }
};

/* ============================ TRACKPAD ============================ */
T.W.trackpad = class extends T.Widget {
  constructor() { super('trackpad', 'TRACKPAD', T.PAL.violet); this.f = new Map(); this.mode = null; this.acc = [0, 0, 0, 0]; this.lastTap = null; this.dragLock = false; this.flash = null; this.maxN = 0; this.gestFired = false; this.pinch0 = 0; }
  pad() { const b = this.body; return { x: b.x, y: b.y + 1, w: b.w, h: b.h - 1 }; }
  down(c) {
    if (!this.f.size) { this.maxN = 0; this.mode = null; this.gestFired = false; this.acc = [0, 0, 0, 0]; }
    this.f.set(c.key, c); this.maxN = Math.max(this.maxN, this.f.size); c.data.lx = c.x; c.data.ly = c.y;
    if (this.f.size === 1 && this.lastTap && T.now() - this.lastTap.t < 280 && T.dist(c.x, c.y, this.lastTap.x, this.lastTap.y) < 18) { this.dragLock = true; T.host.ptr({ op: 'down', btn: 'left' }); this.show('DRAG'); }
    if (this.f.size === 2) { const [a, b] = [...this.f.values()]; this.pinch0 = T.dist(a.x, a.y, b.x, b.y); }
    return true;
  }
  centroid() { let x = 0, y = 0; for (const c of this.f.values()) { x += c.x; y += c.y; } return [x / this.f.size, y / this.f.size]; }
  move(c) {
    const n = this.f.size, dx = c.x - c.data.lx, dy = c.y - c.data.ly; c.data.lx = c.x; c.data.ly = c.y;
    if (n === 1) {
      const v = Math.hypot(c.vx, c.vy), gain = T.clamp(4 + 0.035 * v, 4, 30);   // px per mm, pointer ballistics
      this.acc[0] += dx * gain; this.acc[1] += dy * gain;
      const ix = Math.trunc(this.acc[0]), iy = Math.trunc(this.acc[1]);
      if (ix || iy) { this.acc[0] -= ix; this.acc[1] -= iy; T.host.ptr({ op: 'rel', dx: ix, dy: iy }); }
    } else if (n === 2) {
      const [a, b] = [...this.f.values()], d = T.dist(a.x, a.y, b.x, b.y);
      if (!this.mode) { if (Math.abs(d - this.pinch0) > 10) this.mode = 'zoom'; else if (c.maxD > 4) this.mode = 'scroll'; if (this.mode) this.show(this.mode.toUpperCase()); }
      if (this.mode === 'scroll') {
        this.acc[2] += dy / (2 * 6); this.acc[3] += dx / (2 * 6);              // 6 mm per notch, averaged over 2 fingers
        const ny = Math.trunc(this.acc[2]), nx = Math.trunc(this.acc[3]);
        if (ny) { this.acc[2] -= ny; T.host.ptr({ op: 'wheel', dy: -ny }); }            // natural scrolling: content follows the fingers
        if (nx) { this.acc[3] -= nx; T.host.ptr({ op: 'wheel', dx: -nx }); }
      } else if (this.mode === 'zoom') {
        const r = d / this.pinch0;
        if (r > 1.12 || r < 0.89) { T.host.ptr({ op: 'wheel', dy: r > 1 ? -1 : 1, mods: 'ctrl' }); this.pinch0 = d; }
      }
    } else if (n >= 3 && !this.gestFired) {
      const [cx, cy] = this.centroid(); if (!this.g0) this.g0 = [cx, cy];
      const gx = cx - this.g0[0], gy = cy - this.g0[1];
      const fire = (label, chord) => { this.gestFired = true; this.show(label); T.actions.run({ do: 'key', c: chord }); };
      if (gx > 40) fire('DESKTOP ▶', { win: 'ctrl+win+right', mac: 'ctrl+right', linux: 'ctrl+alt+right' });
      else if (gx < -40) fire('◀ DESKTOP', { win: 'ctrl+win+left', mac: 'ctrl+left', linux: 'ctrl+alt+left' });
      else if (gy < -40) fire('OVERVIEW', { win: 'win+tab', mac: 'ctrl+up', linux: 'super' });
      else if (gy > 40) fire('SHOW DESKTOP', { win: 'win+d', mac: 'cmd+f3', linux: 'super+d' });
    }
  }
  up(c) {
    this.f.delete(c.key);
    if (this.f.size) return;
    this.g0 = null;
    const tap = T.now() - c.t0 < 260 && c.maxD < 5 && !this.mode && !this.gestFired;
    if (this.dragLock) { this.dragLock = false; T.host.ptr({ op: 'up', btn: 'left' }); this.show('DROP'); this.lastTap = null; return; }
    if (tap) {
      const btn = this.maxN >= 3 ? 'middle' : this.maxN === 2 ? 'right' : 'left';
      T.host.ptr({ op: 'click', btn }); if (!T.host.armed) T.host.act({ do: 'click' });
      this.show(btn.toUpperCase() + ' CLICK'); T.fx.ripple(c.x, c.y, btn === 'right' ? T.PAL.ir : T.PAL.violet);
      this.lastTap = btn === 'left' ? { t: T.now(), x: c.x, y: c.y } : null;
    }
  }
  show(label) { this.flash = { label, t: T.now() }; }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue });
    const p = this.pad(), g = G.g;
    g.fillStyle = T.alpha(this.hue, 0.05); G.rr(p.x, p.y, p.w, p.h, 3); g.fill();
    g.fillStyle = T.alpha(this.hue, 0.28);
    for (let x = p.x + 6; x < p.x + p.w - 2; x += 10) for (let y = p.y + 6; y < p.y + p.h - 2; y += 10) g.fillRect(x - 0.35, y - 0.35, 0.7, 0.7);
    for (const c of this.f.values()) {
      g.strokeStyle = T.alpha(this.hue, 0.6); g.lineWidth = 1; g.beginPath(); c.path.forEach((q, i) => (i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]))); g.stroke();
    }
    const hint = '1 finger move · tap click · 2 tap right · 2 drag scroll · pinch zoom · 3 swipe desktops';
    G.fit(hint, p.x + p.w / 2, p.y + p.h - 3, p.w - 6, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
    if (this.flash && now - this.flash.t < 700) G.text(this.flash.label, p.x + p.w / 2, p.y + p.h / 2 + 4, { sz: T.TYPE.big, w: 700, al: 'center', col: T.alpha(this.hue, 1 - (now - this.flash.t) / 700) });
    if (this.dragLock) G.text('DRAG LOCK', p.x + 4, p.y + 8, { sz: T.TYPE.min, w: 700, col: T.PAL.amber });
  }
  targets() { const p = this.pad(); return [Object.assign({ label: 'trackpad' }, p)]; }
};

/* ============================ DIALS + JOG ============================ */
T.W.dials = class extends T.Widget {
  constructor() { super('dials', 'DIALS', T.PAL.amber); this.knobs = []; this.jogSpin = 0; this.jogAngle = 0; this.rate = []; this.ang = [0, 0, 0]; this.fl = {}; }
  kid(k) { return k.kind === 'jog' ? 'jog' : 'k' + k.i; }
  assign() { const p = T.engine.profile || T.PROFILES[0], g = T.PROFILES[0]; return { dials: (p.dials && p.dials.length ? p.dials : g.dials).slice(0, 3), jog: p.jog || g.jog }; }
  layout() {
    const b = this.body, jd = Math.min(b.h - 4, b.w * 0.46);
    const jog = { cx: b.x + jd / 2 + 1, cy: b.y + b.h / 2, r: jd / 2 - 1, kind: 'jog' };
    const area = { x: b.x + jd + 5, y: b.y, w: b.w - jd - 5, h: b.h };
    const n = 3, cols = area.w > area.h * 1.5 ? 3 : 1, rows = Math.ceil(n / cols);
    const cw = area.w / cols, ch = area.h / rows, knobs = [];
    if (cols === 1) {                                          // stacked: knob left, label right
      const r = Math.max(8.5, Math.min(ch / 2 - 3, cw * 0.28));
      for (let i = 0; i < n; i++) knobs.push({ cx: area.x + r + 5, cy: area.y + ch * i + ch / 2, r, i, kind: 'knob', side: true, lw: cw - 2 * r - 12 });
    } else {
      const r = Math.max(9, Math.min(cw, ch) / 2 - 8);
      for (let i = 0; i < n; i++) knobs.push({ cx: area.x + cw * i + cw / 2, cy: area.y + ch / 2 - 4, r, i, kind: 'knob' });
    }
    this.knobs = knobs; this.jog = jog;
  }
  pick(x, y) { this.layout(); for (const k of [this.jog, ...this.knobs]) if (T.dist(x, y, k.cx, k.cy) < k.r + 8) return k; return null; }
  down(c) { const k = this.pick(c.x, c.y); if (!k) return true; c.data.k = k; c.data.a = Math.atan2(c.y - k.cy, c.x - k.cx); c.data.acc = 0; c.data.lin = T.dist(c.x, c.y, k.cx, k.cy) < k.r * 0.28; c.data.hist = []; if (k.kind === 'jog') this.jogSpin = 0; return true; }
  step(k, dir) {
    const now = T.now(); this.rate = this.rate.filter((t) => now - t < 1000); if (this.rate.length > 30) return;   // ≤30 detents/s
    this.rate.push(now);
    const as = this.assign(), m = k.kind === 'jog' ? as.jog : as.dials[k.i]; if (!m) return;
    T.actions.run(dir > 0 ? m.cw : m.ccw);
    this.fl[this.kid(k)] = { dir, t: now };
  }
  move(c) {
    const k = c.data.k; if (!k) return;
    const det = k.kind === 'jog' ? 12 : 15;
    if (c.data.lin) { const d = (c.data.ly ?? c.y0) - c.y; c.data.acc += d / 6 * det; c.data.ly = c.y; }
    else { const a = Math.atan2(c.y - k.cy, c.x - k.cx); let d = a - c.data.a; if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI; c.data.a = a; c.data.acc += d * 180 / Math.PI; if (k.kind === 'jog') { this.jogAngle += d; c.data.hist.push([T.now(), d]); } else this.ang[k.i] += d; }
    while (c.data.acc >= det) { c.data.acc -= det; this.step(k, +1); }
    while (c.data.acc <= -det) { c.data.acc += det; this.step(k, -1); }
  }
  up(c) {
    const k = c.data.k; if (!k) return;
    if (c.maxD < 3 && T.now() - c.t0 < 300) { const as = this.assign(), m = k.kind === 'jog' ? as.jog : as.dials[k.i]; if (m) T.fx.callout(c.x, c.y, (m.l || '') + ': ⟳ ' + T.actions.describe(m.cw) + ' · ⟲ ' + T.actions.describe(m.ccw)); return; }
    if (k.kind === 'jog') { const now = T.now(), recent = c.data.hist.filter((h) => now - h[0] < 110); const w = recent.reduce((s, h) => s + h[1], 0) / 0.11; if (Math.abs(w) > Math.PI) { this.jogSpin = w; this.spinAcc = 0; } }
  }
  tick(dt) {
    if (Math.abs(this.jogSpin) > 0.9) {                     // inertial jog: friction ≈ 0.92 per 16 ms
      const d = this.jogSpin * dt; this.jogAngle += d; this.spinAcc = (this.spinAcc || 0) + d * 180 / Math.PI;
      while (this.spinAcc >= 12) { this.spinAcc -= 12; this.step(this.jog, +1); }
      while (this.spinAcc <= -12) { this.spinAcc += 12; this.step(this.jog, -1); }
      this.jogSpin *= Math.pow(0.92, dt * 60);
    } else this.jogSpin = 0;
  }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue }); this.layout();
    const g = G.g, as = this.assign();
    const drawKnob = (k, label, ang, big) => {
      const f = this.fl[this.kid(k)], fl = f && now - f.t < 220;
      g.fillStyle = T.alpha(this.hue, fl ? 0.22 : 0.07); g.beginPath(); g.arc(k.cx, k.cy, k.r, 0, Math.PI * 2); g.fill();
      G.ring(k.cx, k.cy, k.r, T.alpha(this.hue, 0.8), 1.0);
      const nt = big ? 24 : 24;
      for (let i = 0; i < nt; i++) { const a = ang + (i / nt) * Math.PI * 2, r1 = k.r + 1.5, r2 = k.r + (i % 6 === 0 ? 4.5 : 2.8); G.line(k.cx + Math.cos(a) * r1, k.cy + Math.sin(a) * r1, k.cx + Math.cos(a) * r2, k.cy + Math.sin(a) * r2, T.alpha(this.hue, i % 6 === 0 ? 0.9 : 0.45), 0.6); }
      G.line(k.cx + Math.cos(ang - Math.PI / 2) * k.r * 0.25, k.cy + Math.sin(ang - Math.PI / 2) * k.r * 0.25, k.cx + Math.cos(ang - Math.PI / 2) * k.r * 0.85, k.cy + Math.sin(ang - Math.PI / 2) * k.r * 0.85, T.PAL.ink, 1.4);
      if (big) { for (let i = 0; i < 12; i++) { const a = ang + i / 12 * Math.PI * 2; G.ring(k.cx + Math.cos(a) * k.r * 0.68, k.cy + Math.sin(a) * k.r * 0.68, 2.2, T.alpha(this.hue, 0.5), 0.6); } }
      if (k.side) G.fit(label, k.cx + k.r + 7, k.cy + 2.2, k.lw, { sz: T.TYPE.small, w: 600 });
      else G.fit(label, k.cx, k.cy + k.r + 9.5, k.r * 2 + 16, { sz: T.TYPE.small, w: 600, al: 'center' });
      if (fl) G.text(f.dir > 0 ? '⟳' : '⟲', k.cx, k.cy + 3, { sz: T.TYPE.title, al: 'center', col: T.PAL.ink });
    };
    drawKnob(this.jog, 'JOG · ' + (as.jog ? as.jog.l : ''), this.jogAngle, true);
    this.knobs.forEach((k, i) => drawKnob(k, as.dials[i] ? as.dials[i].l : '—', this.ang[i] || 0, false));
  }
  targets() { this.layout(); return [this.jog, ...this.knobs].map((k) => ({ x: k.cx - k.r, y: k.cy - k.r, w: 2 * k.r, h: 2 * k.r, label: 'dial ' + k.kind })); }
};
