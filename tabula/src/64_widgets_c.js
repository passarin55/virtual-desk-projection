/* ==========================================================================
   TABULA-Ω · widgets (C): scan bay (paper → text → your apps), ink notes,
   true-scale ruler + desk-wide measuring tool.
   ========================================================================== */
'use strict';

/* ============================ SCAN BAY ============================ */
T.W.scan = class extends T.Widget {
  constructor() { super('scan', 'SCAN BAY · PAPER → TEXT', T.PAL.lime); this.state = 'idle'; this.img = null; this.text = ''; this.busy = false; this.flashT = -1e9; this.scroll = 0; this.src = ''; }
  layout() {
    const b = this.body, ratio = 297 / 210;
    let bw = Math.min(297, b.w * 0.56), bh = Math.min(210, b.h - 23);
    if (bw / bh > ratio) bw = bh * ratio; else bh = bw / ratio;
    const bay = { x: b.x + 1, y: b.y + 2, w: bw, h: bh };
    const bx = [], by = bay.y + bay.h + 3, bwid = (bw - 5) / 3;
    [['capture', 'CAPTURE'], ['sample', 'SAMPLE PAGE'], ['clear', 'CLEAR']].forEach(([id, l], i) => bx.push({ id, l, x: bay.x + i * (bwid + 2.5), y: by, w: bwid, h: 16 }));
    const px = bay.x + bw + 6, pw = b.x + b.w - px, res = { x: px, y: b.y + 2, w: pw, h: b.h - 24 };
    const acts = [], aw = (pw - 2.5 * 4) / 5;
    [['copy', 'COPY'], ['type', 'TYPE'], ['ask', 'EXPLAIN'], ['tr', 'TRANSLATE'], ['pin', 'PIN']].forEach(([id, l], i) => acts.push({ id, l, x: px + i * (aw + 2.5), y: b.y + b.h - 17, w: aw, h: 16 }));
    return { bay, bx, res, acts };
  }
  inR(c, r) { return c.x >= r.x && c.x <= r.x + r.w && c.y >= r.y && c.y <= r.y + r.h; }
  down(c) {
    const L = this.layout();
    c.data.b = [...L.bx, ...L.acts].find((r) => this.inR(c, r)) || null;
    c.data.bay = !c.data.b && this.inR(c, L.bay);
    return true;
  }
  up(c) {
    if (c.maxD > 6 || c.cancelled) return;
    const L = this.layout();
    if (c.data.bay && this.img) { this.pointQuery(c, L.bay); return; }
    const b = c.data.b; if (!b || !this.inR(c, b)) return;
    T.fx.ripple(c.x, c.y, this.hue);
    if (b.id === 'capture') this.capture();
    else if (b.id === 'sample') this.sample();
    else if (b.id === 'clear') { this.img = null; this.text = ''; this.state = 'idle'; }
    else if (!this.text) T.fx.callout(c.x, c.y, 'Capture or load a page first');
    else if (b.id === 'copy') { T.host.send({ t: 'clip', op: 'set', text: this.text }); try { navigator.clipboard.writeText(this.text).catch(() => {}); } catch (e) { /* frame may refuse */ } T.fx.callout(c.x, c.y, 'Copied ' + this.text.length + ' chars'); }
    else if (b.id === 'type') T.actions.run({ do: 'text', s: this.text });
    else if (b.id === 'ask') this.vlm('explain', c);
    else if (b.id === 'tr') this.vlm('translate', c);
    else if (b.id === 'pin') { const sh = T.engine.get('shelf'); if (sh) sh.pinned.unshift(this.text.slice(0, 400)); T.fx.callout(c.x, c.y, 'Pinned to the shelf'); }
  }
  /* capture: flood the bay with white (uniform light, and hides our own UI from the camera), then grab */
  async capture() {
    const L = this.layout();
    this.state = 'capture'; this.flashT = T.now(); await T.sleep(160);
    let canvas = null;
    if (T.air.on && T.air.video && T.cfg.calib.H_desk_cam) { canvas = T.W.scan.rectify(T.air.video, L.bay, 4); this.src = 'camera'; }
    else if (T.host.connected && T.host.info && (T.host.info.caps || []).includes('scan')) {
      const W = T.cfg.desk.w, H = T.cfg.desk.h, r = await T.host.request({ t: 'scan', rect: [L.bay.x / W, L.bay.y / H, L.bay.w / W, L.bay.h / H], pxPerMm: 4 }, 12000);
      if (r.ok && r.img) { canvas = await T.W.scan.fromDataURL(r.img); this.src = 'host camera'; }
    }
    if (!canvas) { this.state = 'idle'; T.bus.emit('toast', { text: 'No calibrated camera — use SAMPLE PAGE, or calibrate a webcam (CALIBRATE tab) / host camera', kind: 'warn' }); return; }
    this.img = canvas; this.ocr();
  }
  sample() {
    const c = document.createElement('canvas'); c.width = 1188; c.height = 840; const g = c.getContext('2d');
    g.fillStyle = '#f4f1e8'; g.fillRect(0, 0, c.width, c.height); g.fillStyle = '#1b1b1b';
    g.font = 'bold 44px Georgia, serif'; g.fillText('TABULA-Ω CALIBRATION NOTE', 70, 110);
    g.font = '34px Georgia, serif';
    ['Projector: Epson EF-21, throw ratio 1.03', 'Image 1000 × 562.5 mm at 1030 mm throw', 'Touch band 4–14 mm above desk (Wilson 2010)', 'Re-run Gray-code capture after moving the rig.'].forEach((l, i) => g.fillText(l, 70, 200 + i * 70));
    g.strokeStyle = '#555'; g.lineWidth = 2; g.strokeRect(40, 40, c.width - 80, c.height - 80);
    this.img = c; this.src = 'sample'; this.ocr();
  }
  async ocr() {
    this.state = 'ocr'; this.busy = true; this.text = ''; this.scroll = 0;
    const url = this.img.toDataURL('image/jpeg', 0.85);
    try {
      if (T.host.connected) { const r = await T.host.request({ t: 'vlm', mode: 'ocr', img: url }, 60000); this.text = r.ok ? r.text : '(OCR failed: ' + (r.err || '?') + ')'; }
      else this.text = await T.W.scan.tesseract(this.img);
    } catch (e) { this.text = '(OCR failed: ' + e.message + ')'; }
    this.busy = false; this.state = 'done'; T.log.info('scan', `OCR ${this.text.length} chars from ${this.src}`);
  }
  async vlm(mode, c) {
    this.busy = true; const r = await T.host.request({ t: 'vlm', mode, img: this.img.toDataURL('image/jpeg', 0.8), prompt: mode === 'translate' ? 'Translate to Portuguese (pt-PT).' : '' }, 60000); this.busy = false;
    T.fx.callout(c.x, c.y, r.ok ? r.text : 'VLM unavailable: ' + (r.err || '?'), { maxW: 150, ttl: 9000, col: T.PAL.lime });
  }
  /* tap a word on the paper → crop around the finger → ask the VLM what it is */
  async pointQuery(c, bay) {
    const u = (c.x - bay.x) / bay.w, v = (c.y - bay.y) / bay.h, W = this.img.width, H = this.img.height;
    const cw = W * 0.28, ch = H * 0.12, crop = document.createElement('canvas'); crop.width = cw; crop.height = ch;
    crop.getContext('2d').drawImage(this.img, T.clamp(u * W - cw / 2, 0, W - cw), T.clamp(v * H - ch * 0.8, 0, H - ch), cw, ch, 0, 0, cw, ch);
    T.fx.ripple(c.x, c.y, this.hue);
    const r = await T.host.request({ t: 'vlm', mode: 'explain', img: crop.toDataURL('image/jpeg', 0.85), prompt: 'Explain the word or phrase under the fingertip (centre-bottom of the crop) in one or two sentences.' }, 60000);
    T.fx.callout(c.x, c.y, r.ok ? r.text : 'VLM unavailable: ' + (r.err || '?'), { maxW: 140, ttl: 9000, col: T.PAL.lime });
  }
  static fromDataURL(u) { return new Promise((res) => { const im = new Image(); im.onload = () => { const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; c.getContext('2d').drawImage(im, 0, 0); res(c); }; im.onerror = () => res(null); im.src = u; }); }
  /* perspective-correct crop of a desk rectangle from the camera, using H_desk_cam⁻¹ (desk mm → normalised camera) */
  static rectify(video, rect, pxPerMm) {
    if (!T.cfg.calib.H_desk_cam) return null;
    const vw = video.videoWidth, vh = video.videoHeight, src = document.createElement('canvas'); src.width = vw; src.height = vh;
    const sg = src.getContext('2d'); sg.drawImage(video, 0, 0); const S = sg.getImageData(0, 0, vw, vh).data;
    const ow = Math.round(rect.w * pxPerMm), oh = Math.round(rect.h * pxPerMm), out = document.createElement('canvas'); out.width = ow; out.height = oh;
    const og = out.getContext('2d'), O = og.createImageData(ow, oh);
    for (let y = 0; y < oh; y++) for (let x = 0; x < ow; x++) {
      const [u, v] = T.calib.deskToCam(rect.x + x / pxPerMm, rect.y + y / pxPerMm), sx = Math.round(u * vw), sy = Math.round(v * vh), o = (y * ow + x) * 4;
      if (sx >= 0 && sy >= 0 && sx < vw && sy < vh) { const i = (sy * vw + sx) * 4; O.data[o] = S[i]; O.data[o + 1] = S[i + 1]; O.data[o + 2] = S[i + 2]; } O.data[o + 3] = 255;
    }
    og.putImageData(O, 0, 0); return out;
  }
  static async tesseract(canvas) {
    if (!window.Tesseract) await new Promise((res, rej) => { const s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/tesseract.min.js'; s.onload = res; s.onerror = () => rej(new Error('Tesseract.js could not load (offline or blocked)')); document.head.appendChild(s); });
    const work = (async () => { const w = await window.Tesseract.createWorker('eng'); const r = await w.recognize(canvas); await w.terminate(); return r.data.text.trim(); })();
    return Promise.race([work, T.sleep(25000).then(() => { throw new Error('Tesseract.js did not start (its worker and language data could not be fetched)'); })]);
  }
  isFlashing(now) { return now - this.flashT < 200; }
  draw(G, now) {
    G.frame(this.rect, this.title, { hue: this.hue }); const L = this.layout(), g = G.g, bay = L.bay;
    if (this.isFlashing(now)) { g.fillStyle = '#ffffff'; g.fillRect(bay.x, bay.y, bay.w, bay.h); return; }
    g.strokeStyle = this.hue; g.lineWidth = 1.2; const k = 10;
    for (const [x, y, sx, sy] of [[bay.x, bay.y, 1, 1], [bay.x + bay.w, bay.y, -1, 1], [bay.x + bay.w, bay.y + bay.h, -1, -1], [bay.x, bay.y + bay.h, 1, -1]]) { g.beginPath(); g.moveTo(x + sx * k, y); g.lineTo(x, y); g.lineTo(x, y + sy * k); g.stroke(); }
    if (this.img) { g.globalAlpha = 0.9; g.drawImage(this.img, bay.x + 1, bay.y + 1, bay.w - 2, bay.h - 2); g.globalAlpha = 1; G.text('tap a word → explain', bay.x + bay.w - 3, bay.y + bay.h - 3, { sz: T.TYPE.min, al: 'right', col: '#0a0a0a' }); }
    else {
      G.line(bay.x + 3, bay.y + 3, bay.x + bay.w - 3, bay.y + bay.h - 3, T.alpha(this.hue, 0.12), 0.5);
      G.text(bay.w >= 296 ? 'A4 · 297 × 210 mm' : `${bay.w.toFixed(0)} × ${bay.h.toFixed(0)} mm`, bay.x + bay.w / 2, bay.y + bay.h / 2 - 3, { sz: T.TYPE.body, al: 'center', col: T.alpha(this.hue, 0.8) });
      G.text('place a page, then CAPTURE', bay.x + bay.w / 2, bay.y + bay.h / 2 + 6, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
    }
    for (const b of L.bx) G.button(b, b.l, { hue: this.hue, sz: T.TYPE.min });
    const r = L.res; g.strokeStyle = T.alpha(this.hue, 0.35); g.lineWidth = 0.6; g.strokeRect(r.x, r.y, r.w, r.h);
    if (this.busy) { const a = (now / 300) % (Math.PI * 2); g.strokeStyle = this.hue; g.lineWidth = 1.2; g.beginPath(); g.arc(r.x + r.w / 2, r.y + r.h / 2, 7, a, a + 4); g.stroke(); G.text(this.state === 'ocr' ? 'reading…' : 'asking…', r.x + r.w / 2, r.y + r.h / 2 + 15, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim }); }
    else if (this.text) {
      const lines = G.wrap(this.text, r.w - 6, { sz: T.TYPE.small }), maxL = Math.floor((r.h - 10) / 7);
      lines.slice(this.scroll, this.scroll + maxL).forEach((l, i) => G.text(l, r.x + 3, r.y + 8 + i * 7, { sz: T.TYPE.small, max: r.w - 6 }));
      G.text(`${this.text.length} chars · ${this.src}`, r.x + r.w - 2, r.y + r.h - 2, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim });
    } else G.text('recognised text appears here', r.x + r.w / 2, r.y + r.h / 2, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim });
    for (const b of L.acts) G.button(b, b.l, { hue: this.hue, sz: T.TYPE.min, disabled: !this.text });
  }
  targets() { const L = this.layout(); return [...L.bx, ...L.acts].map((b) => Object.assign({ label: 'scan ' + b.id }, b)); }
};

/* ============================ INK (finger / pen notes) ============================ */
T.W.ink = class extends T.Widget {
  constructor() { super('ink', 'INK · NOTES', T.PAL.beam); this.pages = [[]]; this.pi = 0; this.col = 'beam'; this.wid = 1.2; this.eraser = false; this.live = new Map(); }
  tools() {
    const b = this.body, items = [['c:beam', ''], ['c:ir', ''], ['c:lime', ''], ['c:amber', ''], ['w:0.7', 'fine'], ['w:1.2', 'mid'], ['w:2.4', 'bold'], ['erase', 'ERASE'], ['undo', 'UNDO'], ['clear', 'CLEAR'], ['prev', '◀'], ['next', '▶'], ['ocr', 'TO TEXT']];
    const gd = T.grid({ x: b.x, y: b.y, w: b.w, h: 60 }, items.length, { minW: 17, minH: 16, gap: 2 });
    const rows = Math.ceil(items.length / gd.cols);
    this.canvasR = { x: b.x, y: b.y + rows * (16 + 2) + 1, w: b.w, h: b.h - rows * 18 - 1 };
    return items.map(([id, l], i) => Object.assign({ id, l }, gd.cell(i)));
  }
  down(c) {
    const t = this.tools().find((k) => c.x >= k.x && c.x <= k.x + k.w && c.y >= k.y && c.y <= k.y + k.h); if (t) { c.data.tool = t; return true; }
    const r = this.canvasR; if (c.x < r.x || c.y < r.y || c.x > r.x + r.w || c.y > r.y + r.h) return true;
    if (this.eraser) { c.data.erase = true; this.eraseAt(c.x, c.y); return true; }
    const s = { col: this.col, w: this.wid * (c.kind === 'pen' ? 0.5 + c.pressure : 1), pts: [[c.x, c.y]] }; this.live.set(c.key, s); return true;
  }
  eraseAt(x, y) { const p = this.pages[this.pi]; for (let i = p.length - 1; i >= 0; i--) if (p[i].pts.some((q) => T.dist(q[0], q[1], x, y) < 5)) p.splice(i, 1); }
  move(c) {
    if (c.data.erase) return this.eraseAt(c.x, c.y);
    const s = this.live.get(c.key); if (!s) return; const r = this.canvasR;
    const x = T.clamp(c.x, r.x, r.x + r.w), y = T.clamp(c.y, r.y, r.y + r.h), l = s.pts[s.pts.length - 1];
    if (T.dist(l[0], l[1], x, y) > 0.8) s.pts.push([x, y]);
  }
  up(c) {
    const s = this.live.get(c.key); if (s) { this.live.delete(c.key); if (s.pts.length > 1 || c.maxD < 2) this.pages[this.pi].push(s); return; }
    const t = c.data.tool; if (!t || c.maxD > 6) return;
    T.fx.ripple(c.x, c.y, this.hue);
    if (t.id.startsWith('c:')) { this.col = t.id.slice(2); this.eraser = false; }
    else if (t.id.startsWith('w:')) { this.wid = +t.id.slice(2); this.eraser = false; }
    else if (t.id === 'erase') this.eraser = !this.eraser;
    else if (t.id === 'undo') this.pages[this.pi].pop();
    else if (t.id === 'clear') this.pages[this.pi] = [];
    else if (t.id === 'prev') this.pi = Math.max(0, this.pi - 1);
    else if (t.id === 'next') { this.pi++; if (!this.pages[this.pi]) this.pages[this.pi] = []; }
    else if (t.id === 'ocr') this.toText(c);
  }
  render(pxPerMm = 4) {
    const r = this.canvasR, c = document.createElement('canvas'); c.width = Math.round(r.w * pxPerMm); c.height = Math.round(r.h * pxPerMm);
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); g.setTransform(pxPerMm, 0, 0, pxPerMm, -r.x * pxPerMm, -r.y * pxPerMm);
    for (const s of this.pages[this.pi]) T.W.ink.stroke(g, s, '#111'); return c;
  }
  async toText(c) {
    if (!this.pages[this.pi].length) { T.fx.callout(c.x, c.y, 'Nothing written yet'); return; }
    const r = await T.host.request({ t: 'vlm', mode: 'ocr', img: this.render().toDataURL('image/png'), prompt: 'Transcribe the handwriting exactly. Return only the text.' }, 60000);
    if (r.ok) { const sh = T.engine.get('shelf'); if (sh) sh.pinned.unshift(r.text); T.host.send({ t: 'clip', op: 'set', text: r.text }); }
    T.fx.callout(c.x, c.y, r.ok ? '“' + r.text.slice(0, 140) + '” → clipboard + shelf' : 'Handwriting OCR needs the host VLM: ' + (r.err || '?'), { maxW: 150, ttl: 7000 });
  }
  static stroke(g, s, col) {
    const p = s.pts; g.strokeStyle = col; g.lineWidth = s.w; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); g.moveTo(p[0][0], p[0][1]);
    if (p.length === 1) g.lineTo(p[0][0] + 0.01, p[0][1]);
    for (let i = 1; i < p.length - 1; i++) { const mx = (p[i][0] + p[i + 1][0]) / 2, my = (p[i][1] + p[i + 1][1]) / 2; g.quadraticCurveTo(p[i][0], p[i][1], mx, my); }
    if (p.length > 1) g.lineTo(p[p.length - 1][0], p[p.length - 1][1]); g.stroke();
  }
  draw(G) {
    G.frame(this.rect, this.title, { hue: this.hue }); const g = G.g;
    for (const t of this.tools()) {
      if (t.id.startsWith('c:')) { G.rr(t.x, t.y, t.w, t.h, 2); g.fillStyle = T.PAL[t.id.slice(2)]; g.globalAlpha = this.col === t.id.slice(2) && !this.eraser ? 1 : 0.45; g.fill(); g.globalAlpha = 1; if (this.col === t.id.slice(2) && !this.eraser) { g.strokeStyle = T.PAL.ink; g.lineWidth = 1; g.stroke(); } }
      else G.button(t, t.l, { sz: T.TYPE.min, on: (t.id === 'erase' && this.eraser) || (t.id === 'w:' + this.wid && !this.eraser) });
    }
    const r = this.canvasR; g.strokeStyle = T.alpha(this.hue, 0.3); g.lineWidth = 0.5; g.setLineDash([1.5, 2]); g.strokeRect(r.x, r.y, r.w, r.h); g.setLineDash([]);
    g.save(); g.beginPath(); g.rect(r.x, r.y, r.w, r.h); g.clip();
    for (const s of this.pages[this.pi]) T.W.ink.stroke(g, s, T.PAL[s.col]);
    for (const s of this.live.values()) T.W.ink.stroke(g, s, T.PAL[s.col]);
    g.restore();
    G.text(`page ${this.pi + 1}/${this.pages.length}`, r.x + r.w - 2, r.y + r.h - 2, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim });
  }
  targets() { return this.tools().map((t) => Object.assign({ label: 'ink ' + t.id }, t)); }
};

/* ============================ RULER + MEASURE TOOL ============================ */
T.W.ruler = class extends T.Widget {
  constructor() { super('ruler', 'RULER · MEASURE', T.PAL.amber); this.unit = 'mm'; }
  btns() {
    const b = this.body, items = [['dist', 'DISTANCE'], ['angle', 'ANGLE'], ['area', 'AREA'], ['a4', 'A4 OUTLINE'], ['clear', 'CLEAR'], ['unit', this.unit === 'mm' ? 'mm → in' : 'in → mm']];
    const gd = T.grid({ x: b.x + 12, y: b.y + 12, w: b.w - 14, h: b.h - 14 }, items.length, { minW: 36, minH: 17, maxCols: 2, stretch: true, maxH: 22 });
    return items.map(([id, l], i) => Object.assign({ id, l }, gd.cell(i)));
  }
  down(c) { c.data.b = this.btns().find((k) => c.x >= k.x && c.x <= k.x + k.w && c.y >= k.y && c.y <= k.y + k.h) || null; return true; }
  up(c) {
    const b = c.data.b; if (!b || c.maxD > 6) return; T.fx.ripple(c.x, c.y, this.hue);
    const tool = T.tools.measure;
    if (b.id === 'unit') this.unit = this.unit === 'mm' ? 'in' : 'mm';
    else if (b.id === 'clear') { tool.notes = []; tool.a4 = false; T.engine.activateTool(null); }
    else if (b.id === 'a4') tool.a4 = !tool.a4;
    else { T.engine.activateTool('measure'); tool.mode = b.id; tool.pts = []; T.fx.callout(c.x, c.y, { dist: 'Tap two points anywhere on the desk', angle: 'Tap vertex, then two arms', area: 'Tap corners; tap the first again to close' }[b.id]); }
  }
  draw(G) {
    const r = this.rect, g = G.g; G.frame(r, null, { hue: this.hue });
    const inch = this.unit === 'in', step = inch ? 25.4 / 16 : 1, top = r.y + 1, left = r.x + 1;
    for (let i = 0, x = left; x <= r.x + r.w - 1; i++, x = left + i * step) {
      const major = inch ? i % 16 === 0 : i % 10 === 0, mid = inch ? i % 8 === 0 : i % 5 === 0;
      G.line(x, top, x, top + (major ? 7 : mid ? 4.5 : 2.5), T.alpha(this.hue, major ? 1 : 0.6), major ? 0.6 : 0.35);
      if (major && i) G.text(inch ? String(i / 16) : String(i / 10), x + 0.8, top + 12, { sz: T.TYPE.min, col: T.alpha(this.hue, 0.9), fam: 'mono' });
    }
    for (let i = 0, y = top; y <= r.y + r.h - 1; i++, y = top + i * step) {
      const major = inch ? i % 16 === 0 : i % 10 === 0, mid = inch ? i % 8 === 0 : i % 5 === 0;
      G.line(left, y, left + (major ? 7 : mid ? 4.5 : 2.5), y, T.alpha(this.hue, major ? 1 : 0.6), major ? 0.6 : 0.35);
    }
    G.text(inch ? 'in' : 'cm', r.x + r.w - 3, r.y + 18, { sz: T.TYPE.min, al: 'right', col: T.PAL.dim });
    for (const b of this.btns()) G.button(b, b.l, { hue: this.hue, sz: T.TYPE.small, on: (T.engine.tool === 'measure' && T.tools.measure.mode === b.id) || (b.id === 'a4' && T.tools.measure.a4) });
    G.text('true scale — lay a real ruler here to verify calibration', r.x + r.w / 2, r.y + r.h - 3, { sz: T.TYPE.min, al: 'center', col: T.PAL.dim, max: r.w - 16 });
  }
  targets() { return this.btns().map((b) => Object.assign({ label: 'ruler ' + b.id }, b)); }
};

T.tools = {
  measure: {
    mode: 'dist', pts: [], notes: [], a4: false,
    fmtLen(mm) { const u = T.engine.get('ruler'); return u && u.unit === 'in' ? (mm / 25.4).toFixed(2) + ' in' : mm >= 100 ? (mm / 10).toFixed(1) + ' cm' : mm.toFixed(1) + ' mm'; },
    down(c) {
      const p = [c.x, c.y]; T.fx.ripple(c.x, c.y, T.PAL.amber, 8);
      if (this.mode === 'area' && this.pts.length >= 3 && T.dist(p[0], p[1], this.pts[0][0], this.pts[0][1]) < 10) {
        const a = Math.abs(T.geom.polyArea(this.pts)); this.notes.push({ kind: 'area', pts: this.pts.slice(), label: (a / 100).toFixed(1) + ' cm²' }); this.pts = []; return;
      }
      this.pts.push(p);
      if (this.mode === 'dist' && this.pts.length === 2) { const [a, b] = this.pts; this.notes.push({ kind: 'dist', pts: [a, b], label: this.fmtLen(T.dist(a[0], a[1], b[0], b[1])) }); this.pts = []; }
      if (this.mode === 'angle' && this.pts.length === 3) {
        const [v, a, b] = this.pts, a1 = Math.atan2(a[1] - v[1], a[0] - v[0]), a2 = Math.atan2(b[1] - v[1], b[0] - v[0]);
        let d = Math.abs(a2 - a1) * 180 / Math.PI; if (d > 180) d = 360 - d;
        this.notes.push({ kind: 'angle', pts: [v, a, b], label: d.toFixed(1) + '°' }); this.pts = [];
      }
      if (this.notes.length > 12) this.notes.shift();
    },
    draw(G) {
      const g = G.g, col = T.PAL.amber;
      if (this.a4) {
        const W = T.cfg.desk.w, H = T.cfg.desk.h, w = 297, h = 210, x = (W - w) / 2, y = (H - h) / 2 + 10;
        g.strokeStyle = col; g.lineWidth = 0.8; g.setLineDash([3, 2]); g.strokeRect(x, y, w, h); g.setLineDash([]);
        G.text('A4 · 297 × 210 mm — a real sheet should match exactly', x + w / 2, y - 3, { sz: T.TYPE.min, al: 'center', col });
      }
      const drawNote = (n, live) => {
        const P = n.pts; g.strokeStyle = col; g.lineWidth = 0.9; g.setLineDash(live ? [2, 1.5] : []);
        g.beginPath(); P.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); if (n.kind === 'area') g.closePath(); g.stroke(); g.setLineDash([]);
        P.forEach((p) => { G.line(p[0] - 3, p[1], p[0] + 3, p[1], col, 0.6); G.line(p[0], p[1] - 3, p[0], p[1] + 3, col, 0.6); });
        if (n.label) { const m = P.reduce((s, p) => [s[0] + p[0] / P.length, s[1] + p[1] / P.length], [0, 0]); G.rr(m[0] - 17, m[1] - 10, 34, 8.5, 1.5); g.fillStyle = 'rgba(0,0,0,0.85)'; g.fill(); G.text(n.label, m[0], m[1] - 3.5, { sz: T.TYPE.small, w: 700, al: 'center', col, fam: 'mono' }); }
      };
      for (const n of this.notes) drawNote(n, false);
      if (this.pts.length) drawNote({ kind: this.mode, pts: this.pts }, true);
    },
  },
};
