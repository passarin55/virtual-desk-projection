/* ==========================================================================
   TABULA-Ω · widgets (B): portal (live window mirror you can operate),
   mixer (faders + pads → MIDI), keys, window map, system monitor, timer, shelf.
   ========================================================================== */
'use strict';

/* ============================ PORTAL ============================ */
T.W.portal = class extends T.Widget {
  constructor() {
    super('portal', 'PORTAL', T.PAL.beam);
    this.frame = null; this.target = { follow: true }; this.mode = 'mouse'; this.fps = 0; this.fc = 0; this.ft = 0;
    this.picker = false; this.streaming = false; this.dirty = true; this.lastReq = 0; this.place_ = null; this.tb = [];
    T.bus.on('host:frame', (f) => { if (this.frame && this.frame.bmp && this.frame.bmp.close) this.frame.bmp.close(); this.frame = f; this.fc++; });
    T.bus.on('host:closed', () => { this.streaming = false; this.frame = null; });
    T.bus.on('host:welcome', () => { this.streaming = false; this.dirty = true; });
  }
  toolbar() {
    const b = this.body, y = b.y, h = 16, B = []; let x = b.x;
    for (const [id, l, w] of [['pick', 'WINDOW ▾', 34], ['follow', 'FOLLOW', 28], ['mag', 'MAGNIFY', 30], ['mode', this.mode === 'mouse' ? 'MOUSE' : 'TOUCH', 28]]) { B.push({ id, l, x, y, w, h }); x += w + 2.5; }
    this.tb = B; return B;
  }
  imgArea() { const b = this.body; return { x: b.x, y: b.y + 19, w: b.w, h: b.h - 19 }; }
  placement() {
    const a = this.imgArea(), f = this.frame; if (!f) return null;
    const iw = f.hdr.w || f.bmp.width, ih = f.hdr.h || f.bmp.height, s = Math.min(a.w / iw, a.h / ih);
    return { x: a.x + (a.w - iw * s) / 2, y: a.y + (a.h - ih * s) / 2, w: iw * s, h: ih * s };
  }
  toScreen(x, y) {
    const p = this.placement(); if (!p || !this.frame) return null;
    const u = (x - p.x) / p.w, v = (y - p.y) / p.h; if (u < 0 || v < 0 || u > 1 || v > 1) return null;
    const r = this.frame.hdr.rect || [0, 0, this.frame.hdr.w, this.frame.hdr.h];
    return [Math.round(r[0] + u * r[2]), Math.round(r[1] + v * r[3])];
  }
  tick(dt, now) {
    const want = this.active && T.host.connected;
    if (want && (!this.streaming || this.dirty) && now - this.lastReq > 400) {
      const a = this.imgArea();
      T.host.send({ t: 'portal', op: 'start', target: this.target, fps: 15, maxW: Math.round(Math.min(1600, a.w * T.gfx.s * 1.15)), q: 70 });
      this.streaming = true; this.dirty = false; this.lastReq = now;
    }
    if (!want && this.streaming) { T.host.send({ t: 'portal', op: 'stop' }); this.streaming = false; }
    if (now - this.ft > 1000) { this.fps = this.fc; this.fc = 0; this.ft = now; }
    if (this.mode === 'touch' && now - (this.lastTouchSent || 0) > 500 && T.engine.contactsOf(this).some((k) => k.data.s)) this.sendTouch();   // keep-alive: a finger resting still stays down (host lifts silent contacts after 3 s)
    for (const c of T.engine.contactsOf(this)) {
      const d = c.data; if (!d.pend || this.mode !== 'mouse') continue;
      if (this.held(c, 600, 3)) { d.lp = true; d.pend = false; const s = this.toScreen(c.x0, c.y0); if (s) { T.host.ptr({ op: 'move', x: s[0], y: s[1] }); T.host.ptr({ op: 'click', btn: 'right', x: s[0], y: s[1] }); T.fx.ripple(c.x, c.y, T.PAL.ir); } }
    }
  }
  pickerRows() {
    const a = this.imgArea(), rows = [{ id: 'follow', l: '◎ Follow the focused window' }];
    for (const s of T.host.screens || []) rows.push({ id: 'screen:' + s.id, l: '▭ ' + (s.name || 'Screen ' + s.id) + ` · ${s.w}×${s.h}` });
    for (const w of (T.host.windows || []).filter((w) => !w.min)) rows.push({ id: 'win:' + w.id, l: '▣ ' + w.title });
    return rows.slice(0, Math.floor(a.h / 18.5)).map((r, i) => Object.assign(r, { x: a.x, y: a.y + i * 18.5, w: a.w, h: 16 }));
  }
  down(c) {
    const inR = (b) => c.x >= b.x && c.x <= b.x + b.w && c.y >= b.y && c.y <= b.y + b.h;
    const tb = this.toolbar().find(inR); if (tb) { c.data.tb = tb; return true; }
    if (this.picker) { c.data.row = this.pickerRows().find(inR) || null; return true; }
    const s = this.toScreen(c.x, c.y); if (!s) return true;
    const mine = T.engine.contactsOf(this).filter((k) => k.data.s);
    c.data.s = s;
    if (this.mode === 'touch') { this.sendTouch(null, c); return true; }
    if (mine.length === 1) {
      const o = mine[0]; if (o.data.drag) T.host.ptr({ op: 'up', btn: 'left' }); o.data.pend = false; o.data.drag = false; c.data.two = true; o.data.two = true;
      const mid = this.toScreen((o.x + c.x) / 2, (o.y + c.y) / 2) || s;   // wheel events go to the window under the OS cursor
      T.host.ptr({ op: 'move', x: mid[0], y: mid[1] });
    }
    else c.data.pend = true;
    return true;
  }
  move(c) {
    const d = c.data; if (!d.s) return;
    const s = this.toScreen(c.x, c.y); if (!s) return;
    if (this.mode === 'touch') { d.s = s; this.sendTouch(); return; }
    if (d.two) {
      const ps = T.engine.contactsOf(this).filter((k) => k.data.two); if (ps.length < 2) return;
      const cy = (ps[0].y + ps[1].y) / 2, dist = T.dist(ps[0].x, ps[0].y, ps[1].x, ps[1].y);
      if (this.pz == null) { this.pz = dist; this.py = cy; }
      if (Math.abs(dist - this.pz) > 12) { T.host.ptr({ op: 'wheel', dy: dist > this.pz ? -1 : 1, mods: 'ctrl' }); this.pz = dist; }
      else if (Math.abs(cy - this.py) > 6) { T.host.ptr({ op: 'wheel', dy: cy > this.py ? -1 : 1 }); this.py = cy; }
      return;
    }
    if (d.pend && c.maxD > 3) { d.pend = false; d.drag = true; T.host.ptr({ op: 'move', x: d.s[0], y: d.s[1] }); T.host.ptr({ op: 'down', btn: 'left' }); }
    if (d.drag) T.host.ptr({ op: 'move', x: s[0], y: s[1] });
    d.s = s;
  }
  up(c) {
    const d = c.data;
    if (d.tb) {
      if (c.maxD > 6) return;
      if (d.tb.id === 'pick') { this.picker = !this.picker; if (this.picker) T.host.send({ t: 'win', op: 'list' }); }
      if (d.tb.id === 'follow') { this.target = { follow: true }; this.dirty = true; this.picker = false; }
      if (d.tb.id === 'mag') { this.target = this.target.magnify ? { follow: true } : { magnify: 3 }; this.dirty = true; }
      if (d.tb.id === 'mode') { this.mode = this.mode === 'mouse' ? 'touch' : 'mouse'; if (this.mode === 'touch' && !(T.host.info && (T.host.info.caps || []).includes('touch'))) T.fx.callout(c.x, c.y, 'Host has no OS touch injection — using mouse', { col: T.PAL.amber }); }
      T.fx.ripple(c.x, c.y); return;
    }
    if (this.picker) {
      if (d.row && c.maxD < 6) {
        const id = d.row.id; this.picker = false; this.dirty = true;
        this.target = id === 'follow' ? { follow: true } : id.startsWith('screen:') ? { screen: +id.slice(7) } : { win: +id.slice(4) };
        if (this.target.win) T.host.send({ t: 'win', op: 'focus', id: this.target.win });
      }
      return;
    }
    if (!d.s) return;
    if (this.mode === 'touch') { d.gone = true; this.sendTouch(c); return; }
    if (d.two) { this.pz = null; this.py = null; T.engine.contactsOf(this).forEach((k) => { k.data.two = false; }); return; }
    if (d.pend && !d.lp) { T.host.ptr({ op: 'move', x: d.s[0], y: d.s[1] }); T.host.ptr({ op: 'click', btn: 'left', x: d.s[0], y: d.s[1] }); if (!T.host.armed) T.host.act({ do: 'click' }); T.fx.ripple(c.x, c.y, T.PAL.amber); }
    if (d.drag) { T.host.ptr({ op: 'up', btn: 'left' }); }
  }
  sendTouch(ending, fresh) {
    const live = T.engine.contactsOf(this).filter((k) => k.data.s && k !== ending && k !== fresh);
    if (fresh && fresh.data.s) live.push(fresh);
    const list = live.map((k) => ({ id: k.key, x: k.data.s[0], y: k.data.s[1], phase: k.data.sent ? 'move' : 'down' }));
    if (ending) list.push({ id: ending.key, x: ending.data.s[0], y: ending.data.s[1], phase: 'up' });   // the host ignores an UP for a contact it never saw
    if (T.host.armed) live.forEach((k) => { k.data.sent = true; });
    if (T.host.armed && list.length) { T.host.send({ t: 'touch', contacts: list }); this.lastTouchSent = T.now(); }
  }
  draw(G, now) {
    G.frame(this.rect, null, { hue: this.hue });
    const g = G.g, a = this.imgArea();
    for (const b of this.toolbar()) G.button(b, b.l, { sz: T.TYPE.min, on: (b.id === 'follow' && this.target.follow) || (b.id === 'mag' && this.target.magnify) || (b.id === 'pick' && this.picker) || (b.id === 'mode' && this.mode === 'touch') });
    const tb = this.tb[this.tb.length - 1], tx = tb.x + tb.w + 4;
    const title = this.frame ? (this.frame.hdr.title || 'stream') : T.host.connected ? 'waiting for frames…' : 'host offline';
    G.fit(title, tx, a.y - 7, this.rect.x + this.rect.w - tx - 22, { sz: T.TYPE.min, col: T.PAL.dim });
    G.text(this.fps + ' fps', this.rect.x + this.rect.w - 4, a.y - 7, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim, fam: 'mono' });
    if (this.picker) {
      for (const r of this.pickerRows()) G.button(r, r.l, { sz: T.TYPE.small, hue: T.PAL.violet });
      return;
    }
    const p = this.placement();
    if (!p) { G.text('PORTAL mirrors a window or screen from the host PC — touch it to operate that program.', a.x + a.w / 2, a.y + a.h / 2, { sz: T.TYPE.small, al: 'center', col: T.PAL.dim, max: a.w - 10 }); return; }
    g.imageSmoothingEnabled = true; g.drawImage(this.frame.bmp, p.x, p.y, p.w, p.h);
    g.strokeStyle = T.alpha(this.hue, 0.6); g.lineWidth = 0.6; g.strokeRect(p.x, p.y, p.w, p.h);
    const cur = this.frame.hdr.cursor, r = this.frame.hdr.rect;
    if (cur && r && !this.frame.hdr.sim) { const cx = p.x + (cur[0] - r[0]) / r[2] * p.w, cy = p.y + (cur[1] - r[1]) / r[3] * p.h; if (cx >= p.x && cy >= p.y && cx <= p.x + p.w && cy <= p.y + p.h) G.ring(cx, cy, 3, T.PAL.amber, 0.8); }
    if (this.frame.hdr.sim) G.text('SIMULATED WINDOW', p.x + p.w - 3, p.y + p.h - 3, { sz: T.TYPE.min, al: 'right', col: T.alpha(T.PAL.amber, 0.8) });
  }
  targets() { return this.toolbar().map((b) => Object.assign({ label: 'portal ' + b.id }, b)); }
};

/* ============================ MIXER (faders + pads → MIDI) ============================ */
T.GM_DRUMS = { 35: 'Kick 2', 36: 'Kick', 37: 'Rim', 38: 'Snare', 39: 'Clap', 40: 'Snare 2', 41: 'Low tom', 42: 'Closed hat', 43: 'Tom', 44: 'Pedal hat', 45: 'Low tom', 46: 'Open hat', 47: 'Mid tom', 48: 'Hi-mid tom', 49: 'Crash', 50: 'High tom', 51: 'Ride' };
T.W.mixer = class extends T.Widget {
  constructor() { super('mixer', 'MIXER · MIDI', T.PAL.ir); this.vals = [64, 64, 96, 32]; this.padFlash = new Map(); this.lastSent = [0, 0, 0, 0]; }
  layout() {
    const b = this.body, fw = Math.min(40, (b.w * 0.44 - 9) / 4), faders = [];
    for (let i = 0; i < 4; i++) faders.push({ i, x: b.x + i * (fw + 3), y: b.y + 2, w: fw, h: b.h - 26 });
    const px = b.x + 4 * (fw + 3) + 6, pw = b.x + b.w - px, pads = [];
    const cols = 4, rows = 2, gap = 3, cw = (pw - gap * (cols - 1)) / cols, ch = Math.min(cw, (b.h - 26 - gap) / rows);
    for (let i = 0; i < 8; i++) pads.push({ i, x: px + (i % cols) * (cw + gap), y: b.y + 2 + ((i / cols) | 0) * (ch + gap), w: cw, h: ch });
    const tr = []; const ty = b.y + b.h - 20;
    [['PLAY', 102], ['STOP', 103], ['REC', 104]].forEach(([l, cc], i) => tr.push({ l, cc, x: px + i * ((pw - 6) / 3 + 3), y: ty, w: (pw - 6) / 3, h: 17 }));
    this.L = { faders, pads, tr, fw };
    return this.L;
  }
  hitIn(x, y, arr) { return arr.find((b) => x >= b.x && x <= b.x + b.w && y >= b.y - 3 && y <= b.y + b.h + 3); }
  down(c) {
    const L = this.layout(); T.midi.init();
    const f = this.hitIn(c.x, c.y, L.faders); if (f) { c.data.f = f; this.setF(f, c.y); return true; }
    const p = this.hitIn(c.x, c.y, L.pads); if (p) { c.data.p = p; const note = T.cfg.midi.pads[p.i]; const vel = c.kind === 'pen' ? Math.round(40 + 87 * c.pressure) : 100; this.sent(T.midi.noteOn(note, vel)); this.padFlash.set(p.i, T.now()); T.log.act('midi', `note on ${note} vel ${vel}`); return true; }
    const t = this.hitIn(c.x, c.y, L.tr); if (t) { c.data.t = t; this.sent(T.midi.cc(t.cc, 127)); T.log.act('midi', `CC${t.cc} 127 (${t.l})`); return true; }
    return true;
  }
  sent(ok) { if (!ok && !this.warned) { this.warned = true; T.bus.emit('toast', { text: 'No MIDI output — pick a port in FUNCTIONS (Web MIDI) or arm the host', kind: 'warn' }); } }
  setF(f, y) {
    const v = Math.round(T.clamp((f.y + f.h - y) / f.h, 0, 1) * 127);
    if (v !== this.vals[f.i]) { this.vals[f.i] = v; const now = T.now(); if (now - this.lastSent[f.i] > 12) { this.lastSent[f.i] = now; T.midi.cc(T.cfg.midi.faders[f.i], v); } }
  }
  move(c) { if (c.data.f) this.setF(c.data.f, c.y); }
  up(c) {
    if (c.data.f) T.midi.cc(T.cfg.midi.faders[c.data.f.i], this.vals[c.data.f.i]);
    if (c.data.p) T.midi.noteOff(T.cfg.midi.pads[c.data.p.i]);
    if (c.data.t) T.midi.cc(c.data.t.cc, 0);
  }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue }); const L = this.layout(), g = G.g;
    for (const f of L.faders) {
      const v = this.vals[f.i] / 127, cx = f.x + f.w / 2;
      G.line(cx, f.y + 4, cx, f.y + f.h - 4, T.alpha(this.hue, 0.35), 1.6);
      for (let k = 0; k <= 10; k++) { const yy = f.y + 4 + (f.h - 8) * (1 - k / 10); G.line(f.x + 3, yy, f.x + (k % 5 ? 7 : 10), yy, T.alpha(this.hue, 0.5), 0.5); }
      const cy = f.y + 4 + (f.h - 8) * (1 - v);
      G.line(cx, cy, cx, f.y + f.h - 4, this.hue, 2.4);
      G.rr(cx - f.w * 0.36, cy - 5, f.w * 0.72, 10, 1.5); g.fillStyle = '#000'; g.fill(); g.strokeStyle = T.PAL.ink; g.lineWidth = 0.9; g.stroke();
      G.line(cx - f.w * 0.3, cy, cx + f.w * 0.3, cy, this.hue, 1);
      G.text(String(this.vals[f.i]), cx, f.y + f.h + 7, { sz: T.TYPE.small, al: 'center', fam: 'mono' });
      G.text('CC' + T.cfg.midi.faders[f.i], cx, f.y + f.h + 14, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
    }
    for (const p of L.pads) {
      const t = this.padFlash.get(p.i), k = t ? Math.max(0, 1 - (now - t) / 260) : 0, note = T.cfg.midi.pads[p.i];
      const held = T.engine.contactsOf(this).some((c) => c.data.p && c.data.p.i === p.i);
      G.rr(p.x, p.y, p.w, p.h, 3); g.fillStyle = T.alpha(this.hue, 0.08 + 0.5 * k + (held ? 0.2 : 0)); g.fill(); g.strokeStyle = T.alpha(this.hue, 0.8); g.lineWidth = 1; g.stroke();
      G.fit(T.GM_DRUMS[note] || 'Note ' + note, p.x + p.w / 2, p.y + p.h / 2 + 1, p.w - 4, { sz: T.TYPE.small, w: 600, al: 'center' });
      G.text(String(note), p.x + p.w / 2, p.y + p.h - 4, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim, fam: 'mono' });
    }
    for (const t of L.tr) G.button(t, t.l, { hue: t.l === 'REC' ? T.PAL.red : T.PAL.lime, sz: T.TYPE.small, pressed: T.engine.contactsOf(this).some((c) => c.data.t && c.data.t.l === t.l) });
    const port = T.midi.out ? T.midi.out.name : T.midi.state === 'ready' ? 'no output port' : T.midi.state === 'idle' ? 'touch to enable Web MIDI' : 'Web MIDI ' + T.midi.state;
    G.fit('→ ' + port + ' · ch ' + T.cfg.midi.ch, this.rect.x + this.rect.w - 4, this.rect.y + 7.4, this.rect.w * 0.6, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim });
  }
  targets() { const L = this.layout(); return [...L.faders.map((f) => Object.assign({ label: 'fader' }, f)), ...L.pads.map((p) => Object.assign({ label: 'pad' }, p)), ...L.tr.map((t) => ({ x: t.x, y: t.y, w: t.w, h: t.h, label: 'transport ' + t.l }))]; }
};

/* ============================ KEYS ============================ */
T.KEYSETS = {
  NAV: [['esc', 'tab', 'backspace'], ['home', 'up', 'end'], ['left', 'down', 'right'], ['pageup', 'delete', 'pagedown'], ['enter:2', 'space']],
  NUM: [['numpad7', 'numpad8', 'numpad9', 'numpad_div'], ['numpad4', 'numpad5', 'numpad6', 'numpad_mul'], ['numpad1', 'numpad2', 'numpad3', 'numpad_sub'], ['numpad0:2', 'numpad_dec', 'numpad_add'], ['numpad_enter:4']],
  FN: [['f1', 'f2', 'f3'], ['f4', 'f5', 'f6'], ['f7', 'f8', 'f9'], ['f10', 'f11', 'f12']],
  ABC: [['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'], ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'backspace'], ['z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', 'enter'], ['space:10']],
};
T.KEYLABEL = { esc: 'Esc', tab: 'Tab ⇥', backspace: '⌫', home: 'Home', end: 'End', up: '↑', down: '↓', left: '←', right: '→', pageup: 'PgUp', pagedown: 'PgDn', delete: 'Del', enter: '⏎', space: 'Space', numpad_div: '÷', numpad_mul: '×', numpad_sub: '−', numpad_add: '+', numpad_dec: '.', numpad_enter: 'Enter ⏎' };
T.W.keys = class extends T.Widget {
  constructor() { super('keys', 'KEYS', T.PAL.violet); this.set = 'NAV'; this.mods = new Set(); this.locked = new Set(); this.cells = []; }
  layout() {
    const b = this.body, tabs = [], sets = Object.keys(T.KEYSETS), tw = (b.w - 2.5 * (sets.length - 1)) / sets.length;
    sets.forEach((s, i) => tabs.push({ id: 'set:' + s, l: s, x: b.x + i * (tw + 2.5), y: b.y, w: tw, h: 16 }));
    const modsRow = []; const ml = ['shift', 'ctrl', 'alt', T.targetOS() === 'mac' ? 'cmd' : 'win'], mw = (b.w - 2.5 * 3) / 4;
    ml.forEach((m, i) => modsRow.push({ id: 'mod:' + m, l: { shift: '⇧ Shift', ctrl: T.targetOS() === 'mac' ? '⌃ Ctrl' : 'Ctrl', alt: T.targetOS() === 'mac' ? '⌥ Opt' : 'Alt', cmd: '⌘ Cmd', win: 'Win' }[m], x: b.x + i * (mw + 2.5), y: b.y + b.h - 16, w: mw, h: 16 }));
    const rows = T.KEYSETS[this.set], area = { x: b.x, y: b.y + 19, w: b.w, h: b.h - 38 }, cells = [];
    const narrow = this.set === 'ABC' && area.w < 10 * 15.5;
    if (!narrow) {
      const rh = (area.h - 2.5 * (rows.length - 1)) / rows.length;
      rows.forEach((row, ri) => {
        const units = row.reduce((s, k) => s + (+(k.split(':')[1] || 1)), 0), uw = (area.w - 2.5 * (units - 1)) / units; let x = area.x;
        for (const k of row) { const [key, u = 1] = k.split(':'); const w = uw * u + 2.5 * (u - 1); cells.push({ id: 'key:' + key, key, l: T.KEYLABEL[key] || (key.startsWith('numpad') ? key.slice(6) : key.length === 1 ? key.toUpperCase() : key.toUpperCase()), x, y: area.y + ri * (rh + 2.5), w, h: rh }); x += w + 2.5; }
      });
    }
    this.cells = [...tabs, ...cells, ...modsRow]; this.narrow = narrow; return this.cells;
  }
  at(x, y) { return this.layout().find((c) => x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h); }
  down(c) { c.data.k = this.at(c.x, c.y) || null; return true; }
  move(c) { const k = c.data.k; if (k) { const n = this.at(c.x, c.y); if (!n || n.id !== k.id) c.data.k = null; } }   // slid off: cancel
  up(c) {
    const k0 = c.data.k; if (!k0 || c.cancelled) return;
    const k = this.at(c.x, c.y); if (!k || k.id !== k0.id) return;
    T.fx.ripple(c.x, c.y, this.hue);
    if (k.id.startsWith('set:')) { this.set = k.id.slice(4); return; }
    if (k.id.startsWith('mod:')) { const m = k.id.slice(4); if (this.locked.has(m)) { this.locked.delete(m); this.mods.delete(m); } else if (this.mods.has(m)) this.locked.add(m); else this.mods.add(m); return; }
    const chord = [...this.mods, k.key].join('+');
    T.actions.run({ do: 'key', c: chord });
    for (const m of [...this.mods]) if (!this.locked.has(m)) this.mods.delete(m);
  }
  draw(G) {
    G.frame(this.rect, this.title, { hue: this.hue });
    const pressed = new Set(T.engine.contactsOf(this).map((c) => c.data.k && c.data.k.id).filter(Boolean));
    for (const k of this.layout()) {
      const on = (k.id.startsWith('set:') && k.id.slice(4) === this.set) || (k.id.startsWith('mod:') && this.mods.has(k.id.slice(4)));
      G.button(k, k.l + (k.id.startsWith('mod:') && this.locked.has(k.id.slice(4)) ? ' 🔒' : ''), { hue: k.id.startsWith('mod:') ? T.PAL.amber : this.hue, on, pressed: pressed.has(k.id), sz: k.id.startsWith('set:') ? T.TYPE.min : T.TYPE.body });
    }
    if (this.narrow) { const b = this.body; G.text('QWERTY needs ≥ 160 mm width — use the DEV workspace without a keyboard mask', b.x + b.w / 2, b.y + b.h / 2, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim, max: b.w - 4 }); }
  }
  targets() { return this.layout().map((k) => Object.assign({ label: 'key ' + k.id }, k)); }
};

/* ============================ WINDOW MAP ============================ */
T.W.winmap = class extends T.Widget {
  constructor() { super('winmap', 'WINDOW MAP', T.PAL.violet); this.lastList = 0; this.confirm = null; }
  xf() {
    const S = T.host.screens || []; if (!S.length) return null;
    const minx = Math.min(...S.map((s) => s.x)), miny = Math.min(...S.map((s) => s.y)), maxx = Math.max(...S.map((s) => s.x + s.w)), maxy = Math.max(...S.map((s) => s.y + s.h));
    const b = this.body, area = { x: b.x, y: b.y + 2, w: b.w, h: b.h - 24 }, s = Math.min(area.w / (maxx - minx), area.h / (maxy - miny));
    const ox = area.x + (area.w - (maxx - minx) * s) / 2, oy = area.y + (area.h - (maxy - miny) * s) / 2;
    return { s, to: (x, y) => [ox + (x - minx) * s, oy + (y - miny) * s], from: (x, y) => [(x - ox) / s + minx, (y - oy) / s + miny] };
  }
  wins() { return (T.host.windows || []).filter((w) => !w.min); }
  winAt(x, y) { const X = this.xf(); if (!X) return null; for (const w of this.wins()) { const [a, b] = X.to(w.rect[0], w.rect[1]); if (x >= a && y >= b && x <= a + w.rect[2] * X.s && y <= b + w.rect[3] * X.s) return w; } return null; }
  chips() { const b = this.body, out = []; let x = b.x; for (const w of (T.host.windows || []).filter((w) => w.min)) { const cw = Math.min(70, b.w / 3); if (x + cw > b.x + b.w) break; out.push({ w, x, y: b.y + b.h - 18, w_: cw, h: 16 }); x += cw + 2.5; } return out; }
  tick(dt, now) {
    if (this.active && T.host.connected && now - this.lastList > 2500) { this.lastList = now; T.host.send({ t: 'win', op: 'list' }); }
    for (const c of T.engine.contactsOf(this)) if (c.data.w && this.held(c, 600, 4)) { c.data.lp = true; this.confirm = { id: c.data.w.id, t: T.now() }; }
  }
  down(c) {
    const chip = this.chips().find((k) => c.x >= k.x && c.x <= k.x + k.w_ && c.y >= k.y && c.y <= k.y + k.h); if (chip) { c.data.chip = chip; return true; }
    const w = this.winAt(c.x, c.y); if (w) { c.data.w = w; c.data.r0 = w.rect.slice(); }
    return true;
  }
  move(c) { if (c.data.w && c.maxD > 4) c.data.dragging = true; }
  up(c) {
    const X = this.xf();
    if (c.data.chip && c.maxD < 6) { T.host.send({ t: 'win', op: 'restore', id: c.data.chip.w.id }); T.host.send({ t: 'win', op: 'focus', id: c.data.chip.w.id }); return; }
    const w = c.data.w; if (!w || !X) return;
    if (this.confirm && this.confirm.id === w.id && T.now() - this.confirm.t < 2500 && c.maxD < 5) { this.confirm = null; this.req('close', w); return; }
    const dur = T.now() - c.t0;
    if (c.data.dragging) {
      const vy = (c.y - c.y0) / Math.max(1, dur) * 1000;
      if (dur < 350 && vy < -250) { this.req('max', w); return; }
      if (dur < 350 && vy > 250) { this.req('min', w); return; }
      const dx = (c.x - c.x0) / X.s, dy = (c.y - c.y0) / X.s;
      this.req('move', w, [Math.round(c.data.r0[0] + dx), Math.round(c.data.r0[1] + dy), c.data.r0[2], c.data.r0[3]]);
      return;
    }
    if (c.data.lp) return;
    this.req('focus', w);
  }
  req(op, w, rect) {
    if (!T.host.armed && op !== 'list') { T.host.act({ do: 'win' }); return; }
    T.log.act('win', `${op} “${w.title.slice(0, 40)}”`);
    T.host.send({ t: 'win', op, id: w.id, rect });
  }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue });
    const X = this.xf(), g = G.g, b = this.body;
    if (!X) { G.text('Screens appear once the host connects', b.x + b.w / 2, b.y + b.h / 2, { sz: T.TYPE.small, al: 'center', col: T.PAL.dim }); return; }
    for (const s of T.host.screens) {
      const [x, y] = X.to(s.x, s.y); g.strokeStyle = T.alpha(T.PAL.beam, 0.5); g.lineWidth = 0.8; g.setLineDash([2, 1.5]); g.strokeRect(x, y, s.w * X.s, s.h * X.s); g.setLineDash([]);
      G.text((s.name || 'Screen ' + s.id) + (s.primary ? ' ★' : ''), x + 2, y + s.h * X.s - 2.5, { sz: T.TYPE.min, col: T.PAL.dim });
    }
    const drag = T.engine.contactsOf(this).find((c) => c.data.dragging);
    const ws = this.wins().slice().reverse();
    for (const w of ws) {
      let [x, y] = X.to(w.rect[0], w.rect[1]); const ww = w.rect[2] * X.s, hh = w.rect[3] * X.s;
      if (drag && drag.data.w === w) { x += drag.x - drag.x0; y += drag.y - drag.y0; }
      const focused = T.host.focus && w.title && T.host.focus.title && T.host.focus.title === w.title;
      const conf = this.confirm && this.confirm.id === w.id && now - this.confirm.t < 2500;
      g.fillStyle = conf ? T.alpha(T.PAL.red, 0.25) : T.alpha(this.hue, focused ? 0.2 : 0.08); g.fillRect(x, y, ww, hh);
      g.strokeStyle = conf ? T.PAL.red : T.alpha(this.hue, focused ? 1 : 0.7); g.lineWidth = focused ? 1.2 : 0.8; g.strokeRect(x, y, ww, hh);
      G.fit(conf ? 'TAP AGAIN TO CLOSE' : w.title, x + 2, y + 6.5, Math.max(8, ww - 4), { sz: T.TYPE.min, col: conf ? T.PAL.red : T.PAL.ink });
    }
    for (const k of this.chips()) G.button({ x: k.x, y: k.y, w: k.w_, h: k.h }, '▁ ' + k.w.title, { sz: T.TYPE.min, hue: T.PAL.dim });
    G.fit('tap focus · drag move · flick ↑ maximise · flick ↓ minimise · hold then tap = close', b.x + b.w / 2, b.y + b.h - 22, b.w, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
  }
  targets() { const X = this.xf(); if (!X) return []; return this.wins().map((w) => { const [x, y] = X.to(w.rect[0], w.rect[1]); return { x, y, w: w.rect[2] * X.s, h: w.rect[3] * X.s, label: 'window ' + w.title.slice(0, 20) }; }); }
};

/* ============================ SYSTEM MONITOR ============================ */
T.W.sysmon = class extends T.Widget {
  constructor() { super('sysmon', 'SYSTEM · GPU · MODELS', T.PAL.ir); this.hist = { cpu: [], gpu: {}, rx: [], tx: [] };
    T.bus.on('host:telemetry', (m) => { const H = this.hist, P = (a, v) => { a.push(v); if (a.length > 90) a.shift(); }; P(H.cpu, m.cpu || 0); if (m.net) { P(H.rx, m.net.rx || 0); P(H.tx, m.net.tx || 0); } for (const gp of m.gpus || []) { H.gpu[gp.index] = H.gpu[gp.index] || []; P(H.gpu[gp.index], gp.util || 0); } });
  }
  spark(G, a, x, y, w, h, max, col) {
    const g = G.g; if (a.length < 2) return; g.beginPath();
    a.forEach((v, i) => { const px = x + (i / (a.length - 1)) * w, py = y + h - T.clamp(v / max, 0, 1) * h; i ? g.lineTo(px, py) : g.moveTo(px, py); });
    g.strokeStyle = col; g.lineWidth = 0.8; g.stroke(); g.lineTo(x + w, y + h); g.lineTo(x, y + h); g.closePath(); g.fillStyle = T.alpha(col, 0.12); g.fill();
    G.disc(x + w, y + h - T.clamp(a[a.length - 1] / max, 0, 1) * h, 1.1, col);
  }
  draw(G) {
    G.frame(this.rect, this.title, { hue: this.hue });
    const tm = T.host.telemetry, b = this.body, g = G.g;
    if (!tm) { G.text('Telemetry arrives from the host (psutil, nvidia-smi, Ollama /api/ps)', b.x + b.w / 2, b.y + b.h / 2, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim, max: b.w - 4 }); return; }
    let y = b.y + 2;
    G.text('CPU', b.x, y + 7, { sz: T.TYPE.small, w: 700 }); G.text(Math.round(tm.cpu) + '%', b.x + b.w, y + 7, { sz: T.TYPE.small, al: 'right', fam: 'mono' });
    this.spark(G, this.hist.cpu, b.x + 18, y, b.w - 38, 10, 100, T.PAL.beam); y += 14;
    if (tm.mem) { G.text(`RAM ${tm.mem.used.toFixed(1)} / ${tm.mem.total} GB`, b.x, y + 6, { sz: T.TYPE.min, col: T.PAL.dim }); g.fillStyle = T.alpha(T.PAL.lime, 0.18); g.fillRect(b.x + b.w * 0.5, y + 2, b.w * 0.5, 4); g.fillStyle = T.PAL.lime; g.fillRect(b.x + b.w * 0.5, y + 2, b.w * 0.5 * tm.mem.used / tm.mem.total, 4); y += 10; }
    for (const gp of tm.gpus || []) {
      if (y > b.y + b.h - 30) break;
      G.fit(gp.name, b.x, y + 6, b.w * 0.55, { sz: T.TYPE.min, w: 700 });
      G.text(`${Math.round(gp.util)}% · ${Math.round(gp.temp)}°C · ${Math.round(gp.power || 0)} W`, b.x + b.w, y + 6, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim, fam: 'mono' });
      this.spark(G, this.hist.gpu[gp.index] || [], b.x, y + 8, b.w * 0.55, 8, 100, T.PAL.ir);
      const vr = gp.memUsed / gp.memTotal; g.fillStyle = T.alpha(T.PAL.amber, 0.18); g.fillRect(b.x + b.w * 0.6, y + 11, b.w * 0.4, 4); g.fillStyle = T.PAL.amber; g.fillRect(b.x + b.w * 0.6, y + 11, b.w * 0.4 * vr, 4);
      G.text(`${gp.memUsed.toFixed(1)}/${gp.memTotal} GB`, b.x + b.w, y + 21, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim, fam: 'mono' });
      y += 25;
    }
    if (tm.ollama && y < b.y + b.h - 8) {
      G.text('MODELS LOADED', b.x, y + 6, { sz: T.TYPE.min, w: 700, col: T.PAL.beam }); y += 8;
      for (const m of tm.ollama) { if (y > b.y + b.h - 4) break; G.fit(`${m.name}  ${(m.vram / 1e9).toFixed(1)} GB`, b.x + 2, y + 6, b.w - 2, { sz: T.TYPE.min, fam: 'mono' }); y += 7; }
    }
  }
};

/* ============================ TIMER (object-anchorable) ============================ */
T.W.timer = class extends T.Widget {
  constructor() { super('timer', 'TIMER', T.PAL.lime); this.dur = 25 * 60; this.left = this.dur; this.running = false; this.tEnd = 0; this.done = 0; }
  start(sec) { this.dur = sec; this.left = sec; this.running = true; this.tEnd = T.now() + sec * 1000; this.done = 0; }
  geo() { const b = this.body, presetH = 17, r = Math.max(14, Math.min(b.w, b.h - presetH - 6) / 2 - 3); return { cx: b.x + b.w / 2, cy: b.y + r + 2, r, presets: [5, 15, 25, 50].map((m, i) => ({ m, x: b.x + i * ((b.w - 7.5) / 4 + 2.5), y: b.y + b.h - presetH, w: (b.w - 7.5) / 4, h: presetH })) }; }
  down(c) {
    const G_ = this.geo(), d = T.dist(c.x, c.y, G_.cx, G_.cy);
    const p = G_.presets.find((p) => c.x >= p.x && c.x <= p.x + p.w && c.y >= p.y && c.y <= p.y + p.h); if (p) { c.data.p = p; return true; }
    if (Math.abs(d - G_.r) < 12) { c.data.ring = true; this.running = false; } else if (d < G_.r) c.data.center = true;
    return true;
  }
  move(c) {
    if (!c.data.ring) return; const G_ = this.geo();
    let a = Math.atan2(c.y - G_.cy, c.x - G_.cx) + Math.PI / 2; if (a < 0) a += Math.PI * 2;
    this.dur = Math.max(60, Math.round(a / (Math.PI * 2) * 60) * 60); this.left = this.dur;
  }
  up(c) {
    if (c.data.p) { this.start(c.data.p.m * 60); T.fx.ripple(c.x, c.y, this.hue); return; }
    if (c.data.center && c.maxD < 5) { if (this.running) { this.running = false; } else { if (this.left <= 0) this.left = this.dur; this.running = true; this.tEnd = T.now() + this.left * 1000; } T.fx.ripple(c.x, c.y, this.hue); }
  }
  tick(dt, now) {
    if (!this.running) return;
    this.left = Math.max(0, (this.tEnd - now) / 1000);
    if (this.left <= 0) { this.running = false; this.done = now; T.bus.emit('toast', { text: 'Timer finished', kind: 'ok' }); T.log.info('timer', 'finished ' + Math.round(this.dur / 60) + ' min'); }
  }
  ringAt(G, cx, cy, r, now, lw = 2.2) {
    const g = G.g, k = this.dur ? this.left / this.dur : 0, blink = this.done && now - this.done < 5000 && Math.floor(now / 250) % 2;
    G.ring(cx, cy, r, T.alpha(this.hue, 0.2), lw);
    g.strokeStyle = blink ? T.PAL.amber : this.hue; g.lineWidth = lw; g.beginPath(); g.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + k * Math.PI * 2); g.stroke();
  }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue }); const q = this.geo();
    this.ringAt(G, q.cx, q.cy, q.r, now, 2.4);
    for (let i = 0; i < 60; i++) { const a = i / 60 * Math.PI * 2 - Math.PI / 2, r1 = q.r - 3.5, r2 = q.r - (i % 5 ? 5 : 7); G.line(q.cx + Math.cos(a) * r1, q.cy + Math.sin(a) * r1, q.cx + Math.cos(a) * r2, q.cy + Math.sin(a) * r2, T.alpha(this.hue, i % 5 ? 0.3 : 0.7), 0.5); }
    const m = Math.floor(this.left / 60), s = Math.floor(this.left % 60);
    G.text(`${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`, q.cx, q.cy + 4, { sz: Math.min(T.TYPE.huge, q.r * 0.55), w: 600, al: 'center', fam: 'mono' });
    G.text(this.running ? 'tap to pause' : 'tap to start · drag ring to set', q.cx, q.cy + q.r * 0.45, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
    for (const p of q.presets) G.button(p, p.m + ' min', { hue: this.hue, sz: T.TYPE.small });
  }
  /* anchored ring around a tracked mug / token (drawn by the engine overlay) */
  drawAnchors(G, now) { if (!this.running && !(this.done && now - this.done < 5000)) return; for (const o of T.engine.objects) if (o.kind === 'mug' || o.tag === 'timer') this.ringAt(G, o.x, o.y, (o.r || 45) + 7, now, 3); }
  targets() { const q = this.geo(); return q.presets.map((p) => Object.assign({ label: 'timer preset' }, p)).concat([{ x: q.cx - q.r, y: q.cy - q.r, w: 2 * q.r, h: 2 * q.r, label: 'timer ring' }]); }
};

/* ============================ SHELF (clipboard history) ============================ */
T.W.shelf = class extends T.Widget {
  constructor() { super('shelf', 'CLIPBOARD SHELF', T.PAL.amber); this.mode = 'paste'; this.hidden = new Set(); this.pinned = []; this.scroll = 0; }
  items() { const seen = new Set(), out = []; for (const it of [...this.pinned.map((t) => ({ text: t, pin: true })), ...(T.host.clip || [])]) { if (seen.has(it.text) || this.hidden.has(it.text)) continue; seen.add(it.text); out.push(it); } return out; }
  cards() { const b = this.body, top = b.y + 19, ch = 22, n = Math.floor((b.h - 20) / (ch + 2.5)); return this.items().slice(this.scroll, this.scroll + n).map((it, i) => ({ it, x: b.x, y: top + i * (ch + 2.5), w: b.w, h: ch })); }
  modeBtn() { const b = this.body; return { x: b.x, y: b.y, w: b.w, h: 16 }; }
  down(c) { const m = this.modeBtn(); if (c.y <= m.y + m.h) { c.data.mode = true; return true; } c.data.card = this.cards().find((k) => c.y >= k.y && c.y <= k.y + k.h) || null; return true; }
  up(c) {
    if (c.data.mode && c.maxD < 5) { this.mode = this.mode === 'paste' ? 'type' : 'paste'; return; }
    const k = c.data.card; if (!k) return;
    if (c.x - c.x0 < -40) { this.hidden.add(k.it.text); return; }
    if (Math.abs(c.y - c.y0) > 12) { this.scroll = T.clamp(this.scroll + (c.y < c.y0 ? 1 : -1) * 2, 0, Math.max(0, this.items().length - 1)); return; }
    if (c.data.lp) return;
    T.fx.ripple(c.x, c.y, this.hue);
    T.actions.run(this.mode === 'paste' ? { do: 'paste', text: k.it.text } : { do: 'text', s: k.it.text });
  }
  tick() { for (const c of T.engine.contactsOf(this)) if (c.data.card && this.held(c, 600)) { c.data.lp = true; const t = c.data.card.it.text; if (this.pinned.includes(t)) this.pinned = this.pinned.filter((x) => x !== t); else this.pinned.unshift(t); T.fx.callout(c.x, c.y, this.pinned.includes(t) ? 'Pinned' : 'Unpinned'); } }
  draw(G) {
    G.frame(this.rect, this.title, { hue: this.hue }); const g = G.g;
    G.button(this.modeBtn(), this.mode === 'paste' ? 'TAP = PASTE (clipboard + ' + T.chord.pretty('mod+v') + ')' : 'TAP = TYPE AS KEYSTROKES', { sz: T.TYPE.min, hue: this.hue, on: true });
    const cards = this.cards();
    if (!cards.length) { const b = this.body; G.text('Copied text appears here', b.x + b.w / 2, b.y + b.h / 2, { sz: T.TYPE.small, al: 'center', col: T.PAL.dim }); }
    for (const k of cards) {
      G.rr(k.x, k.y, k.w, k.h, 2); g.fillStyle = T.alpha(this.hue, 0.07); g.fill(); g.strokeStyle = T.alpha(this.hue, k.it.pin ? 0.95 : 0.45); g.lineWidth = 0.8; g.stroke();
      if (k.it.secret) G.text('•••••••• ' + k.it.text.length + ' chars · looks like a secret — tap still pastes it', k.x + 3, k.y + 8, { sz: T.TYPE.small, max: k.w - 6, col: T.PAL.dim });
      else G.wrap(k.it.text.replace(/\s+/g, ' '), k.w - 6, { sz: T.TYPE.small }).slice(0, 2).forEach((l, i) => G.text(l, k.x + 3, k.y + 8 + i * 6.8, { sz: T.TYPE.small, max: k.w - 6 }));
      if (k.it.t) G.text(T.W.shelf.ago(k.it.t), k.x + k.w - 3, k.y + k.h - 2, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim });
      if (k.it.pin) G.text('●', k.x + k.w - 3, k.y + 7, { sz: T.TYPE.min, al: 'right', col: this.hue });
    }
  }
  static ago(t) { const s = (Date.now() - t) / 1000; return s < 60 ? Math.round(s) + ' s' : s < 3600 ? Math.round(s / 60) + ' min' : Math.round(s / 3600) + ' h'; }
  targets() { return [this.modeBtn(), ...this.cards()].map((k) => ({ x: k.x, y: k.y, w: k.w, h: k.h, label: 'shelf' })); }
};
