/* ==========================================================================
   TABULA-Ω · operator console (the monitor side). Tabs: desk, scheme,
   calibrate, functions, tribunal, dossier, link. Talks to the leader through
   T.call so it works both standalone and as a follower of a projector window.
   ========================================================================== */
'use strict';

const $ = (s) => document.querySelector(s), $$ = (s) => [...document.querySelectorAll(s)];
T.ui = {
  tab: 'desk', pinSel: 0, pinDrag: null, meshDrag: null, lastPin: 0, objDrag: null,

  init() {
    this.tabs(); this.header(); this.desk(); this.scheme(); this.calib(); this.funcs(); this.tribunal(); this.dossier(); this.linkTab(); this.inspector();
    T.bus.on('toast', (t) => this.toast(t.text, t.kind));
    T.bus.on('cfg:changed', () => { this.syncControls(); if (this.tab === 'scheme') this.renderScheme(); });
    setInterval(() => this.refresh(), 250);
    this.syncControls();
    const saved = T.cfg.ui.tab; if (saved && saved !== 'desk') this.show(saved);
    if (location.hash && /^#(desk|scheme|calib|funcs|tribunal|dossier|link)$/.test(location.hash)) this.show(location.hash.slice(1));
  },
  toast(text, kind = 'info') {
    const el = document.createElement('div'); el.className = 'toast ' + (kind === 'warn' ? 'warn' : kind === 'ok' ? 'ok' : kind === 'bad' ? 'bad' : ''); el.textContent = text;
    $('#toasts').appendChild(el); setTimeout(() => el.remove(), 4200);
    if (T.link.isLeader() && T.gfx.g) T.fx.callout(T.cfg.desk.w / 2, 70, text, { col: kind === 'warn' ? T.PAL.amber : kind === 'bad' ? T.PAL.red : T.PAL.beam, ttl: 3200 });
  },

  /* ---------------- tabs ---------------- */
  tabs() { for (const b of $$('nav.tabs button')) b.addEventListener('click', () => this.show(b.dataset.tab)); },
  show(tab) {
    this.tab = tab;
    for (const b of $$('nav.tabs button')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const s of $$('section.tab')) s.hidden = s.dataset.panel !== tab;
    if (T.cfg.ui.tab !== tab) { T.cfg.ui.tab = tab; T.saveCfg(); }
    if (tab === 'scheme') this.renderScheme();
    if (tab === 'tribunal') this.renderTribunal();
    if (tab === 'funcs') this.renderFuncs();
  },

  /* ---------------- header ---------------- */
  header() {
    $('#btnProject').addEventListener('click', () => T.proj.enter(true));
    $('#btnProjWin').addEventListener('click', () => {
      const w = window.open(location.href.split('#')[0] + '#projector' + (T.runToken ? '&t=' + encodeURIComponent(T.runToken) : ''), 'tabula-projector', 'popup,width=1280,height=720');
      if (!w) this.toast('The browser blocked the popup. Open this page again with #projector at the end of the address, on the projector screen.', 'warn');
    });
  },
  chips() {
    const h = T.host, c = [];
    c.push([h.mode === 'sim' ? 'HOST · SIMULATED' : h.mode === 'off' ? 'HOST · OFF' : h.connected ? 'HOST · LIVE' : h.needToken ? 'HOST · NEEDS TOKEN' : 'HOST · CONNECTING', h.mode === 'sim' ? 'beam' : h.connected ? 'ok' : 'warn']);
    c.push([!h.connected ? 'NOT ARMED' : h.armed ? (h.mode === 'sim' ? 'ARMED · SIM' : 'ARMED · LIVE INPUT') : 'SAFE', h.armed && h.mode !== 'sim' ? 'bad' : h.armed ? 'beam' : 'ok']);
    c.push(['WS · ' + T.engine.ws + (T.engine.auto ? ' · AUTO' : ''), '']);
    c.push([(T.engine.stats.fps || 0) + ' FPS', T.engine.stats.fps && T.engine.stats.fps < 40 ? 'warn' : '']);
    c.push([T.cfg.calib.H_desk_cam ? `CAM ${T.cfg.calib.rmsMm.toFixed(2)} mm` : 'CAM UNCALIBRATED', T.cfg.calib.H_desk_cam ? 'ok' : 'warn']);
    if (T.air.on) c.push(['AIR ' + T.air.fps + ' FPS', 'ok']);
    c.push([T.link.isLeader() ? (T.link.role === 'projector' ? 'PROJECTOR WINDOW' : 'CONSOLE LEADS') : 'FOLLOWING PROJECTOR', T.link.isLeader() ? '' : 'beam']);
    const html = c.map(([t, k]) => `<span class="chip ${k}">${T.escapeHTML(t)}</span>`).join('');
    if (html !== this._chips) { $('#chips').innerHTML = html; this._chips = html; }
  },

  /* ---------------- DESK ---------------- */
  desk() {
    const seg = $('#wsSeg');
    seg.innerHTML = [...Object.keys(T.WORKSPACES), 'AUTO'].map((n) => `<button type="button" data-ws="${n}" aria-pressed="false">${n}</button>`).join('');
    seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.ws === 'AUTO') T.call('setAuto', { on: !T.engine.auto }); else T.call('setWorkspace', { name: b.dataset.ws }); });
    const sf = $('#simFocus'); sf.innerHTML = T.SIM_APPS.map((a, i) => `<option value="${i}">${T.escapeHTML(a.app)} — ${T.escapeHTML(a.title)}</option>`).join('');
    sf.addEventListener('change', () => T.call('simFocus', { i: +sf.value }));
    $('#tray').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return; const k = b.dataset.obj, W = T.cfg.desk.w, H = T.cfg.desk.h;
      let list = (T.engine.simObjects || []).slice();
      if (k === 'clear') list = [];
      else if (k === 'mug') list.push({ id: T.uid('o'), kind: 'mug', x: W * 0.83, y: H * 0.3, r: 42 });
      else if (k === 'phone') list.push({ id: T.uid('o'), kind: 'phone', x: W * 0.45, y: H * 0.35, w: 75, h: 155 });
      else if (k === 'notebook') list.push({ id: T.uid('o'), kind: 'notebook', x: W * 0.12, y: H * 0.45, w: 148, h: 210 });
      T.call('simObjects', { list });
    });
    const cv = $('#deskView');
    const toDesk = (cx, cy) => { const r = cv.getBoundingClientRect(); return [(cx - r.left) / r.width * T.cfg.desk.w, (cy - r.top) / r.height * T.cfg.desk.h]; };
    // physical objects can be dragged before anything else sees the pointer
    cv.addEventListener('pointerdown', (e) => {
      if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
      const [x, y] = toDesk(e.clientX, e.clientY);
      const o = (T.engine.simObjects || []).slice().reverse().find((o) => (o.r ? T.dist(x, y, o.x, o.y) < o.r : Math.abs(x - o.x) < o.w / 2 && Math.abs(y - o.y) < o.h / 2));
      if (o) { this.objDrag = { id: o.id, dx: o.x - x, dy: o.y - y }; e.stopImmediatePropagation(); e.preventDefault(); cv.setPointerCapture(e.pointerId); }
    }, true);
    cv.addEventListener('pointermove', (e) => {
      if (!this.objDrag) return; e.stopImmediatePropagation(); const [x, y] = toDesk(e.clientX, e.clientY);
      const list = T.engine.simObjects.map((o) => (o.id === this.objDrag.id ? Object.assign({}, o, { x: x + this.objDrag.dx, y: y + this.objDrag.dy }) : o));
      T.engine.simObjects = list; T.call('simObjects', { list });
    }, true);
    const endObj = (e) => { if (this.objDrag) { e.stopImmediatePropagation(); this.objDrag = null; } };
    cv.addEventListener('pointerup', endObj, true); cv.addEventListener('pointercancel', endObj, true);
    this.simPtr = new T.SimPointer(cv, toDesk, (phase, id, x, y, extra) => T.call('pointer', { phase, id, x, y, extra }));
    $('#optGrid').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { grid: e.target.checked } } }));
    $('#optHand').addEventListener('change', (e) => T.call('patchCfg', { patch: { input: { simHand: e.target.checked } } }));
    $('#optKb').addEventListener('change', (e) => T.call('patchCfg', { patch: { desk: { kb: { on: e.target.checked } } } }));
    $('#handSeg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) T.call('patchCfg', { patch: { desk: { handed: b.dataset.h } } }); });
  },
  drawDesk() {
    const cv = $('#deskView'), W = T.cfg.desk.w, H = T.cfg.desk.h, want = Math.round(1600 * H / W);
    if (cv.height !== want) cv.height = want;
    const g = cv.getContext('2d'), s = cv.width / W;
    g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, cv.height);
    const src = T.link.isLeader() ? T.render.surface : T.link.pvBmp;
    if (src) g.drawImage(src, 0, 0, cv.width, cv.height);
    g.setTransform(s, 0, 0, s, 0, 0);
    const kb = T.engine.kbRect();
    if (kb) { // the physical keyboard, drawn as an object lying on the projection
      g.fillStyle = 'rgba(38,40,44,0.92)'; g.beginPath(); g.roundRect ? g.roundRect(kb.x, kb.y, kb.w, kb.h, 8) : g.rect(kb.x, kb.y, kb.w, kb.h); g.fill();
      g.fillStyle = 'rgba(80,84,92,0.9)'; const kw = 15.5, gap = 3.5; for (let r = 0; r < 5; r++) for (let x = kb.x + 12; x < kb.x + kb.w - 14; x += kw + gap) g.fillRect(x, kb.y + 12 + r * (kw + gap), kw, kw * 0.92);
    }
    for (const o of T.engine.simObjects || []) {
      g.save(); g.shadowColor = 'rgba(0,0,0,0.5)'; g.shadowBlur = 10; g.fillStyle = o.kind === 'mug' ? 'rgba(214,208,196,0.93)' : o.kind === 'phone' ? 'rgba(24,26,30,0.95)' : 'rgba(170,52,48,0.9)';
      if (o.r) { g.beginPath(); g.arc(o.x, o.y, o.r, 0, 7); g.fill(); g.shadowBlur = 0; g.strokeStyle = 'rgba(120,112,100,0.9)'; g.lineWidth = 6; g.beginPath(); g.arc(o.x + o.r + 6, o.y, 14, -1.2, 1.2); g.stroke(); g.fillStyle = 'rgba(60,40,28,0.9)'; g.beginPath(); g.arc(o.x, o.y, o.r * 0.78, 0, 7); g.fill(); }
      else { g.fillRect(o.x - o.w / 2, o.y - o.h / 2, o.w, o.h); if (o.kind === 'phone') { g.shadowBlur = 0; g.fillStyle = 'rgba(70,90,110,0.6)'; g.fillRect(o.x - o.w / 2 + 4, o.y - o.h / 2 + 8, o.w - 8, o.h - 16); } else { g.shadowBlur = 0; g.fillStyle = 'rgba(0,0,0,0.25)'; g.fillRect(o.x - o.w / 2, o.y - o.h / 2, 10, o.h); } }
      g.restore();
    }
    for (const hp of T.input.hostHands || []) { if (hp.length < 3) continue; g.fillStyle = 'rgba(255,92,147,0.18)'; g.strokeStyle = 'rgba(255,92,147,0.7)'; g.lineWidth = 1.2; g.beginPath(); hp.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath(); g.fill(); g.stroke(); }
    for (const o of T.engine.hostObjects || []) { if (o.kind === 'token') continue; g.strokeStyle = 'rgba(255,200,97,0.8)'; g.setLineDash([4, 3]); g.lineWidth = 1.2; g.strokeRect(o.x - o.w / 2, o.y - o.h / 2, o.w, o.h); g.setLineDash([]); }
    if (T.cfg.input.simHand) for (const hp of T.input.hands || []) { g.fillStyle = 'rgba(226,186,158,0.36)'; g.strokeStyle = 'rgba(226,186,158,0.7)'; g.lineWidth = 1.2; g.beginPath(); hp.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.closePath(); g.fill(); g.stroke(); }
    if (!T.link.isLeader() && !src) { g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = '#7cf0ff'; g.font = '600 22px ' + T.FONT.ui; g.fillText('waiting for the projector window…', 30, 50); }
  },

  /* ---------------- SCHEME ---------------- */
  scheme() {
    const sc = T.cfg.scheme;
    const opt = (o, v) => Object.entries(o).map(([k, p]) => `<option value="${k}"${k === v ? ' selected' : ''}>${T.escapeHTML(p.name || p)}</option>`).join('');
    $('#schemeForm').innerHTML = `
      <label class="f">Projector<select id="scProj">${opt(T.PROJECTORS, sc.projector)}</select></label>
      <label class="f">Mount<select id="scMount"><option value="overhead">Overhead, lens pointing down</option><option value="fold">Horizontal + 45° fold mirror</option><option value="tilt">Angled arm (keystone)</option></select></label>
      <label class="f">Lens → mirror d₁ (mm)<input type="number" id="scD1" min="80" max="900" step="10"></label>
      <label class="f">Image width on desk (mm)<input type="number" id="scW" min="300" max="2400" step="10"></label>
      <label class="f">Room light on the desk<select id="scAmb"><option value="500">500 lx · office (EN 12464-1)</option><option value="300">300 lx · dimmed</option><option value="200">200 lx · evening lamp</option><option value="100">100 lx · dark studio</option></select></label>
      <label class="f">Lumens derating<input type="number" id="scDer" min="0.3" max="1" step="0.05"></label>
      <label class="f">Depth sensor<select id="scSens">${opt(T.SENSORS, sc.sensor)}</select></label>
      <label class="f">Sensor height (mm)<input type="number" id="scSH" min="80" max="3000" step="10"></label>
      <label class="f">Eye distance (mm)<input type="number" id="scVD" min="300" max="1200" step="10"></label>
      <label class="f">Viewing elevation (°)<input type="number" id="scVE" min="20" max="90" step="1"></label>
      <label class="f">Projector refresh (Hz)<select id="scHz"><option>60</option><option>50</option><option>120</option></select></label>
      <label class="f">Mains (Hz)<select id="scMains"><option>50</option><option>60</option></select></label>`;
    const bind = (id, key, num = true) => $(id).addEventListener('change', (e) => { const v = num ? +e.target.value : e.target.value; if (key === 'deskW') T.call('patchCfg', { patch: { desk: { w: v, h: v * this.aspect() } } }); else T.call('patchCfg', { patch: { scheme: { [key]: v } } }); });
    bind('#scProj', 'projector', false); bind('#scMount', 'mount', false); bind('#scD1', 'd1'); bind('#scW', 'deskW'); bind('#scAmb', 'ambient'); bind('#scDer', 'derate');
    bind('#scSens', 'sensor', false); bind('#scSH', 'sensorH'); bind('#scVD', 'viewDist'); bind('#scVE', 'viewElev'); bind('#scHz', 'projHz'); bind('#scMains', 'mains');
    $('#btnAspect').addEventListener('click', () => { const r = T.scheme.compute(); T.call('patchCfg', { patch: { desk: { h: +r.H.toFixed(1) }, output: { res: r.P.res.slice() } } }).then(() => { T.render.resize(); this.toast(`Desk set to ${r.W} × ${r.H.toFixed(1)} mm at ${r.P.res.join('×')}`, 'ok'); }); });
    $('#checklist').innerHTML = ['Point the lens axis straight at the desk (or use the fold mirror) — no projector keystone.', 'Switch the projector to game / low-latency mode; disable motion smoothing, noise reduction and auto-keystone.', 'Matte, light desk surface (gain ≈ 1.0). Gloss throws a hotspot into your eyes when you lean in.', 'Mount the depth sensor next to the lens, as low as its minimum range allows (depth precision halves when the distance doubles).', 'Lock the webcam exposure to a multiple of the projector frame (DLP) and of the lighting flicker.', 'RG1/RG2 projectors only; keep the head guard on; nobody should see the lens from a normal seated gaze.', '50 cm clearance at intake and exhaust; exhaust away from the mirror and cameras (heat shimmer shifts calibration).', 'Run CALIBRATE → corner pin, Gray-code, accuracy test, then the TRIBUNAL before arming.'].map((s) => `<li>${s}</li>`).join('');
  },
  aspect() { const P = T.scheme.proj(T.cfg.scheme); return P.res[1] / P.res[0]; },
  renderScheme() {
    const sc = T.cfg.scheme;
    $('#scProj').value = sc.projector; $('#scMount').value = sc.mount; $('#scD1').value = sc.d1; $('#scW').value = T.cfg.desk.w; $('#scAmb').value = String(sc.ambient); $('#scDer').value = sc.derate;
    $('#scSens').value = sc.sensor; $('#scSH').value = sc.sensorH; $('#scVD').value = sc.viewDist; $('#scVE').value = sc.viewElev; $('#scHz').value = String(sc.projHz); $('#scMains').value = String(sc.mains);
    $('#scD1').disabled = sc.mount !== 'fold';
    const r = T.scheme.compute(), f = (v, d = 0) => T.fmt(v, d);
    const mis = Math.abs(r.H - T.cfg.desk.h) > 1;
    $('#aspectNote').textContent = mis ? `Desk is ${f(T.cfg.desk.w)} × ${f(T.cfg.desk.h, 1)} mm; this projector's image is ${f(r.W)} × ${f(r.H, 1)} mm.` : `Desk matches the projector: ${f(r.W)} × ${f(r.H, 1)} mm.`;
    const card = (title, big, sub, rows) => `<div class="panel"><h2>${title}</h2><div class="bigstat">${big}<small>${sub}</small></div><dl class="kv" style="margin-top:10px">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>`;
    const lat = r.lat.map(([k, v]) => `<div class="bar"><span>${k}</span><i style="width:${Math.min(100, v / Math.max(150, r.total) * 100)}%"></i><b>${f(v, 1)} ms</b></div>`).join('');
    $('#schemeStats').innerHTML =
      card('THROW &amp; MOUNT', `${f(r.D)} mm`, `lens → desk (ratio ${r.Tr} × ${f(r.W)} mm)`, [
        ['mount', r.fold ? `fold: d₁ ${f(r.d1)} + d₂ ${f(r.d2)} mm` : r.tilt ? `tilted ${f(r.key.alpha, 0)}° · ${f(r.key.usable * 100)} % rows kept` : 'overhead, axis ⟂ desk'],
        ['lens offset', `${r.P.offset} % — lens above the image ${r.P.offset >= 100 ? 'far edge' : 'centre'}`],
        ['mirror', r.mirror ? `${Math.ceil(r.mirror.wM)} × ${Math.ceil(r.mirror.LM)} mm first-surface (orientation ${r.mirror.good})` : '—'],
        ['orientation', r.P.orient]]) +
      card('BRIGHTNESS &amp; CONTRAST', `${f(r.iscr, 1)} : 1`, r.cls, [
        ['on-desk illuminance', `${f(r.E)} lx (${r.P.lm} lm × ${T.cfg.scheme.derate} / ${f(r.A, 3)} m²)`],
        ['white / black luminance', `${f(r.Lw)} / ${f(r.Lb)} cd/m²`],
        ['lumens for 7 · 15 · 50 : 1', `${f(r.need(7))} · ${f(r.need(15))} · ${f(r.need(50))} lm`],
        ['colour', r.P.color]]) +
      card('PIXELS &amp; LEGIBILITY', `${f(r.pitch, 2)} mm/px`, `${r.P.res.join(' × ')} over ${f(r.W)} mm`, r.leg.map((l) => [`${l.am}′ cap height`, `${f(l.mm, 1)} mm = ${f(l.px, 1)} px (font ≥ ${f(l.em, 1)} mm)`]).concat([['foreshortening', `× ${f(r.elev, 2)} at ${T.cfg.scheme.viewElev}°`]])) +
      card('SENSING', r.band ? `${f(r.band.lo)}–${f(r.band.hi)} mm` : r.S.kind, r.band ? 'touch band above the desk' : 'contact method', [
        ['footprint', `${f(r.fp[0])} × ${f(r.fp[1])} mm ${r.covers ? '✓ covers image' : '✗ too small'}`],
        ['depth pixel', `${f(r.depthPx, 1)} mm`], ['range', `${r.S.range.join('–')} m ${r.inRange ? '✓' : '✗ out of range'}`],
        ['expected error', `≈ ${f(r.acc, 1)} mm worst case · ${f(r.accFused, 1)} mm with IR fusion`], ['target minimum', `${f(r.minTarget)} mm`]]) +
      `<div class="panel"><h2>LATENCY BUDGET</h2><div class="bigstat">${f(r.total)} ms<small>touch → photon estimate · tap threshold 69 ms · drag 11 ms (Deber 2015)</small></div><div class="bars" style="margin-top:10px">${lat}</div></div>` +
      card('CAMERA EXPOSURE', `${f(r.expo.common, 1)} ms`, r.expo.seq ? 'DLP + lighting common multiple' : 'lighting flicker multiple', [
        ['projector frame', `${f(r.expo.projFrame, 2)} ms`], ['light flicker (2 × mains)', `${f(r.expo.lightFlicker, 1)} ms`], ['why', r.expo.seq ? 'shorter exposures sample partial DLP bit-planes → bands' : '3LCD shows RGB together; only room flicker matters']]);
    $('#svgSide').innerHTML = T.scheme.sideSVG(r); $('#svgTop').innerHTML = T.scheme.topSVG(r);
    $('#bom').innerHTML = '<tr><th>Part</th><th>Specification</th><th>Why / note</th></tr>' + T.scheme.bom(r).map((b) => `<tr><td><b>${b[0]}</b></td><td>${T.escapeHTML(b[1])}</td><td class="muted">${T.escapeHTML(b[2])}</td></tr>`).join('');
  },

  /* ---------------- CALIBRATE ---------------- */
  calib() {
    const cv = $('#pinView');
    const pos = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
    cv.addEventListener('pointerdown', (e) => {
      const [u, v] = pos(e), c = T.cfg.output.corners; let best = -1, bd = 0.04;
      c.forEach((p, i) => { const d = Math.hypot((p[0] - u) * 16 / 9, p[1] - v); if (d < bd) { bd = d; best = i; } });
      if (best >= 0) { this.pinSel = best; this.pinDrag = { i: best }; cv.setPointerCapture(e.pointerId); return; }
      const m = T.cfg.output.mesh; if (m.on) { const H = T.cornerH(); for (let j = 0; j < m.ny; j++) for (let i = 0; i < m.nx; i++) { const p = T.warpPoint(H, i / (m.nx - 1), j / (m.ny - 1)); if (Math.hypot((p[0] - u) * 16 / 9, p[1] - v) < 0.025) { this.meshDrag = { i, j, H }; cv.setPointerCapture(e.pointerId); return; } } }
    });
    cv.addEventListener('pointermove', (e) => {
      const [u, v] = pos(e);
      if (this.pinDrag) { const c = T.cfg.output.corners.map((p) => p.slice()); c[this.pinDrag.i] = [T.clamp(u, -0.25, 1.25), T.clamp(v, -0.25, 1.25)]; this.patchThrottled({ output: { corners: c } }); }
      if (this.meshDrag) { const m = T.cfg.output.mesh, { i, j, H } = this.meshDrag, base = T.m3.apply(H, i / (m.nx - 1), j / (m.ny - 1)), d = (m.d || new Array(m.nx * m.ny).fill(null).map(() => [0, 0])).map((x) => (x ? x.slice() : [0, 0])); d[j * m.nx + i] = [u - base[0], v - base[1]]; this.patchThrottled({ output: { mesh: { d } } }); }
    });
    const end = () => { this.pinDrag = null; this.meshDrag = null; };
    cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
    cv.addEventListener('keydown', (e) => {
      const k = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key]; if (!k) { if (/^[1-4]$/.test(e.key)) this.pinSel = +e.key - 1; return; }
      e.preventDefault(); const st = e.shiftKey ? 10 : 1, [rw, rh] = T.cfg.output.res, c = T.cfg.output.corners.map((p) => p.slice());
      c[this.pinSel] = [c[this.pinSel][0] + k[0] * st / rw, c[this.pinSel][1] + k[1] * st / rh]; T.call('patchCfg', { patch: { output: { corners: c } } });
    });
    $('#pinReset').addEventListener('click', () => T.call('patchCfg', { patch: { output: { corners: [[0, 0], [1, 0], [1, 1], [0, 1]], mesh: { d: null } } } }));
    $('#pinGrid').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { grid: e.target.checked } } }));
    $('#pinFlipX').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { flipX: e.target.checked } } }));
    $('#pinFlipY').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { flipY: e.target.checked } } }));
    $('#pinMesh').addEventListener('change', (e) => { const m = T.cfg.output.mesh; T.call('patchCfg', { patch: { output: { mesh: { on: e.target.checked, d: m.d || new Array(m.nx * m.ny).fill(null).map(() => [0, 0]) } } } }); });
    $('#outRes').addEventListener('change', (e) => { const [w, h] = e.target.value.split('x').map(Number); T.call('patchCfg', { patch: { output: { res: [w, h] } } }).then(() => T.render.resize()); });
    for (const [id, key] of [['#outGain', 'gain'], ['#outFeather', 'feather']]) $(id).addEventListener('input', (e) => this.patchThrottled({ output: { [key]: +e.target.value } }));
    for (const [id, i] of [['#tintR', 0], ['#tintG', 1], ['#tintB', 2]]) $(id).addEventListener('input', (e) => { const t = T.cfg.output.tint.slice(); t[i] = +e.target.value; this.patchThrottled({ output: { tint: t } }); });
    $('#optDim').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { dimHands: e.target.checked } } }));
    $('#optHead').addEventListener('change', (e) => T.call('patchCfg', { patch: { output: { headGuard: e.target.checked } } }));
    $('#gcSettle').addEventListener('change', (e) => T.call('patchCfg', { patch: { calib: { settleMs: +e.target.value } } }));
    $('#gcRun').addEventListener('click', async () => {
      $('#gcRun').disabled = true; $('#gcStats').innerHTML = '<dt>status</dt><dd>projecting patterns…</dd>';
      const res = await T.call('gray', { src: $('#gcSrc').value, step: +$('#gcStep').value, settleMs: +$('#gcSettle').value });
      $('#gcRun').disabled = false; this.showGray(res);
    });
    $('#gcCancel').addEventListener('click', () => T.call('grayCancel'));
    T.bus.on('calib:progress', (p) => { $('#gcProg').style.width = ((p.k + 1) / p.n * 100).toFixed(1) + '%'; });
    $('#accRun').addEventListener('click', () => { T.call('accStart', { rounds: +$('#accRounds').value }); this.toast('Tap the centre of each ring on the desk', 'ok'); if (this.tab !== 'desk' && !T.render.projecting) this.show('desk'); });
    $('#accStop').addEventListener('click', () => T.call('accStop'));
    T.bus.on('calib:accdone', () => this.showAcc());
    $('#latRun').addEventListener('click', async () => { $('#latOut').textContent = 'measuring…'; const r = await T.call('latency'); $('#latOut').textContent = r.ok ? `median ${r.med.toFixed(0)} ms (${r.samples.map((x) => x.toFixed(0)).join(', ')})` : r.err; });
    $('#airRun').addEventListener('click', async () => {
      if (T.air.on) { await T.call('airStop'); return; }
      if (!T.cfg.calib.H_desk_cam) this.toast('Calibrate the camera first (Gray-code with the webcam) so hands map onto the desk', 'warn');
      $('#airOut').textContent = 'loading MediaPipe…'; const ok = await T.call('airStart'); $('#airOut').textContent = ok ? 'running' : (T.air.err || 'failed');
    });
    $('#airSeg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) T.call('patchCfg', { patch: { input: { air: b.dataset.m } } }); });
    this.showAcc();
  },
  patchThrottled(patch) {
    this._pp = this._pp ? T.deepMerge(this._pp, patch) : patch;
    if (this._ppT) return;
    this._ppT = setTimeout(() => { const p = this._pp; this._pp = null; this._ppT = null; T.call('patchCfg', { patch: p }); }, 33);
  },
  showGray(res) {
    if (!res) return;
    const rows = [['patterns', `${res.plan ? res.plan.n : '—'} (${res.plan ? res.plan.bx + '+' + res.plan.by : ''} bits)`], ['camera', `${res.camW}×${res.camH} · ${res.src}`], ['decoded pixels', res.decoded], ['stripe cells', res.cells], ['time', res.ms + ' ms']];
    if (res.ok) rows.push(['inliers', `${res.inliers} (${(res.ratio * 100).toFixed(0)} %)`], ['RMS', `${res.rms.toFixed(2)} px · ${res.rmsMm.toFixed(2)} mm`], ['condition', res.cond.toFixed(1)]);
    if (res.truthMm != null) rows.push(['ground truth', res.truthMm.toFixed(2) + ' mm RMS']);
    if (!res.ok) rows.push(['error', res.err]);
    $('#gcStats').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${T.escapeHTML(String(v))}</dd>`).join('');
    if (res.viz) { const c = $('#gcViz'); c.width = res.viz.w; c.height = res.viz.h; c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(res.viz.data), res.viz.w, res.viz.h), 0, 0); }
    if (res.ok) this.toast(`Camera calibrated: ${res.rmsMm.toFixed(2)} mm RMS`, 'ok'); else this.toast('Gray-code: ' + res.err, 'warn');
  },
  showAcc() {
    const a = T.cfg.calib.accuracy;
    $('#accStats').innerHTML = a ? [['source', a.src], ['taps', a.n], ['offset removed', `${a.bias[0].toFixed(1)}, ${a.bias[1].toFixed(1)} mm`], ['spread (SD)', `${a.sd[0].toFixed(1)} × ${a.sd[1].toFixed(1)} mm`], ['R95', a.r95.toFixed(1) + ' mm'], ['safe target', a.minTarget.toFixed(0) + ' mm']].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('') : '<dt>status</dt><dd>not measured yet</dd>';
  },
  drawPin(now) {
    if (now - this.lastPin < 100) return; this.lastPin = now;
    const cv = $('#pinView'), g = cv.getContext('2d'), W = cv.width, H = cv.height;
    if (T.link.isLeader() && T.render.surface) T.warp2d(g, T.render.surface, W, H, { nx: 12, ny: 7 }); else { g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = '#000'; g.fillRect(0, 0, W, H); }
    const Hm = T.cornerH(); if (!Hm) return;
    g.strokeStyle = 'rgba(124,240,255,0.35)'; g.lineWidth = 1;
    for (let i = 0; i <= 10; i++) { g.beginPath(); for (let j = 0; j <= 20; j++) { const p = T.warpPoint(Hm, i / 10, j / 20); j ? g.lineTo(p[0] * W, p[1] * H) : g.moveTo(p[0] * W, p[1] * H); } g.stroke(); }
    for (let j = 0; j <= 6; j++) { g.beginPath(); for (let i = 0; i <= 20; i++) { const p = T.warpPoint(Hm, i / 20, j / 6); i ? g.lineTo(p[0] * W, p[1] * H) : g.moveTo(p[0] * W, p[1] * H); } g.stroke(); }
    g.strokeStyle = '#ffc861'; g.setLineDash([6, 5]); g.strokeRect(1, 1, W - 2, H - 2); g.setLineDash([]);
    g.font = '600 13px ' + T.FONT.ui; g.fillStyle = '#ffc861'; g.fillText('projector output ' + T.cfg.output.res.join('×'), 8, H - 8);
    T.cfg.output.corners.forEach((p, i) => { g.beginPath(); g.arc(p[0] * W, p[1] * H, 11, 0, 7); g.fillStyle = i === this.pinSel ? 'rgba(255,200,97,0.9)' : 'rgba(124,240,255,0.85)'; g.fill(); g.fillStyle = '#000'; g.font = '700 13px ' + T.FONT.ui; g.textAlign = 'center'; g.fillText(String(i + 1), p[0] * W, p[1] * H + 4.5); g.textAlign = 'left'; });
    const m = T.cfg.output.mesh; if (m.on) for (let j = 0; j < m.ny; j++) for (let i = 0; i < m.nx; i++) { const p = T.warpPoint(Hm, i / (m.nx - 1), j / (m.ny - 1)); g.fillStyle = '#ff5c93'; g.fillRect(p[0] * W - 5, p[1] * H - 5, 10, 10); }
  },

  /* ---------------- FUNCTIONS ---------------- */
  funcs() {
    const ps = $('#profSel'); ps.addEventListener('change', () => this.renderProfile());
    $('#midiEnable').addEventListener('click', async () => { const r = await T.call('midiInit'); this.midiPorts(r); });
    $('#midiOut').addEventListener('change', (e) => T.call('midiPick', { id: e.target.value }));
    $('#midiTest').addEventListener('click', async () => { const r = await T.call('midiTest'); this.toast(r && r.ok ? 'Sent note 60 on channel ' + T.cfg.midi.ch : 'No MIDI output available', r && r.ok ? 'ok' : 'warn'); });
    $('#midiCh').addEventListener('change', (e) => T.call('patchCfg', { patch: { midi: { ch: T.clamp(+e.target.value || 1, 1, 16) } } }));
    const nums = (s, n) => { const a = s.split(/[\s,]+/).map(Number).filter((x) => Number.isInteger(x) && x >= 0 && x <= 127); return a.length === n ? a : null; };
    $('#midiCC').addEventListener('change', (e) => { const a = nums(e.target.value, 4); if (a) T.call('patchCfg', { patch: { midi: { faders: a } } }); else this.toast('Enter 4 CC numbers 0–127', 'warn'); });
    $('#midiNotes').addEventListener('change', (e) => { const a = nums(e.target.value, 8); if (a) T.call('patchCfg', { patch: { midi: { pads: a } } }); else this.toast('Enter 8 note numbers 0–127', 'warn'); });
    $('#macroApply').addEventListener('click', () => {
      try { const m = JSON.parse($('#macroJson').value); if (!Array.isArray(m) || !m.every((x) => x.id && x.l && Array.isArray(x.steps))) throw new Error('need [{id, l, steps:[…]}]'); T.call('patchCfg', { patch: { macros: m } }); $('#macroMsg').textContent = `✓ ${m.length} macros applied`; }
      catch (e) { $('#macroMsg').textContent = '✗ ' + e.message; }
    });
    $('#macroReset').addEventListener('click', () => { T.call('patchCfg', { patch: { macros: T.deepClone(T.DEFAULT_MACROS) } }).then(() => this.renderFuncs()); });
    $('#userProfApply').addEventListener('click', () => {
      try { const p = JSON.parse($('#userProfJson').value || '[]'); if (!Array.isArray(p) || !p.every((x) => x.id && x.name && Array.isArray(x.buttons))) throw new Error('need [{id, name, match, buttons:[…]}]'); p.forEach((x) => { x.glyph = x.glyph || '★'; x.ws = x.ws || 'DEV'; x.match = x.match || {}; }); T.call('patchCfg', { patch: { userProfiles: p } }); $('#userProfMsg').textContent = `✓ ${p.length} profiles`; this.renderFuncs(); }
      catch (e) { $('#userProfMsg').textContent = '✗ ' + e.message; }
    });
    $('#userProfExample').addEventListener('click', () => { $('#userProfJson').value = JSON.stringify([{ id: 'qgis', name: 'QGIS', glyph: 'Q', ws: 'MAKE', match: { exe: ['qgis-bin.exe', 'qgis'], title: 'qgis' }, buttons: [{ l: 'Pan', a: { do: 'key', c: 'space' }, g: 'nav' }, { l: 'Zoom full', a: { do: 'key', c: 'mod+shift+f' }, g: 'view' }, { l: 'Identify', a: { do: 'key', c: 'mod+shift+i' }, g: 'tool' }], dials: [{ l: 'Zoom', cw: { do: 'wheel', dy: -1 }, ccw: { do: 'wheel', dy: 1 } }] }], null, 2); });
    $('#cfgCopy').addEventListener('click', () => { const t = $('#cfgJson'); try { navigator.clipboard.writeText(t.value).then(() => { $('#cfgMsg').textContent = '✓ copied'; }, () => { t.select(); $('#cfgMsg').textContent = 'selected — press Ctrl/⌘+C'; }); } catch (e) { t.select(); $('#cfgMsg').textContent = 'selected — press Ctrl/⌘+C'; } });
    $('#cfgLoad').addEventListener('click', () => { try { const c = JSON.parse($('#cfgJson').value); if (!c || c.v !== T.defaults().v) throw new Error('not a TABULA v' + T.defaults().v + ' config'); T.call('replaceCfg', { cfg: c }).then(() => { $('#cfgMsg').textContent = '✓ loaded'; this.syncControls(); }); } catch (e) { $('#cfgMsg').textContent = '✗ ' + e.message; } });
    if (T.BOOT) { const d = $('#cfgDownload'); d.hidden = false; d.addEventListener('click', () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(T.cfg, null, 1)], { type: 'application/json' })); a.download = 'tabula-config.json'; a.click(); }); }
    let armReset = 0;
    $('#cfgFactory').addEventListener('click', (e) => {
      if (Date.now() - armReset > 3000) { armReset = Date.now(); e.target.textContent = 'Click again to reset'; setTimeout(() => { e.target.textContent = 'Factory reset'; }, 3000); return; }
      T.call('replaceCfg', { cfg: T.defaults() }).then(() => { e.target.textContent = 'Factory reset'; $('#cfgMsg').textContent = '✓ defaults restored'; this.syncControls(); });
    });
  },
  midiPorts(r) { const s = $('#midiOut'); if (!r || !r.ports) return; s.innerHTML = r.ports.length ? r.ports.map((p) => `<option value="${T.escapeHTML(p.id)}"${p.id === r.out ? ' selected' : ''}>${T.escapeHTML(p.name)}</option>`).join('') : `<option value="">no output ports (${r.state})</option>`; },
  renderFuncs() {
    const cat = [
      ['Rail', 'always', 'Workspaces, focused app, SAFE/ARMED pill (hold 2 s to arm), clock, CPU/GPU, media keys, PANIC.'],
      ['Palette', 'all', 'Shortcut wall for the focused program (22 built-in profiles); follows focus or pins; long-press shows the chord.'],
      ['Macro deck', 'DEV · PAPER · STUDIO · OPS', 'Multi-step actions: keys, text, launch/run (host allow-list), OBS, timers, workspace jumps.'],
      ['Trackpad', 'all', 'Relative mouse with ballistics; tap/2-tap/3-tap clicks, double-tap-drag, 2-finger scroll, pinch zoom, 3-finger desktop swipes.'],
      ['Portal', 'DEV · MAKE', 'Live JPEG stream of any window/screen; touch it to click, drag, scroll or pinch that program; magnifier; OS touch injection.'],
      ['Dials + jog', 'MAKE · STUDIO', 'Three rotary encoders + inertial jog wheel; per-app mappings (brush size, timeline, orbit, zoom, history scrub).'],
      ['Mixer', 'STUDIO', '4 faders (CC), 8 velocity pads (GM drum notes), transport CCs → Web MIDI or host MIDI.'],
      ['Keys', 'DEV', 'NAV / NUM / FN / QWERTY keysets with sticky and locking modifiers.'],
      ['Scan bay', 'PAPER', 'Flash-illuminated capture of paper → OCR (local VLM / Tesseract) → copy, type, explain, translate, pin; tap a word to explain it.'],
      ['Ink', 'MAKE · PAPER', 'Finger/pen notes with pressure, pages, eraser; handwriting → text → clipboard + shelf.'],
      ['Ruler', 'MAKE', 'True-scale mm/inch rule; desk-wide distance, angle and area measurement; A4 outline to verify scale.'],
      ['Shelf', 'DEV · STUDIO · PAPER · OPS', 'Clipboard history from the host; tap to paste or type into the focused app; pin and swipe away.'],
      ['Window map', 'OPS', 'All monitors and windows to scale; tap to focus, drag to move, flick to maximise/minimise, hold-tap to close.'],
      ['System', 'OPS', 'CPU/RAM, every NVIDIA GPU (util, VRAM, temp, power) and the models Ollama has loaded.'],
      ['Timer', 'OPS', 'Pomodoro ring; drag to set; anchors a progress ring around a mug on the desk.'],
      ['AIR hands', 'calibration', 'Webcam MediaPipe hand tracking; pinch or dwell to press.'],
      ['Depth touch', 'host', 'Wilson-band + DIRECT-style fingertip engine on RealSense / Orbbec / Kinect; palm-slam panic; hover.'],
      ['Tangibles', 'host', 'ArUco MIP 36h12 tokens tracked by the host camera; mugs, phones, notebooks push the UI aside.'],
    ];
    $('#catalog').innerHTML = '<tr><th>Function</th><th>Workspaces</th><th>What it does</th></tr>' + cat.map((c) => `<tr><td><b>${c[0]}</b></td><td class="muted">${c[1]}</td><td>${c[2]}</td></tr>`).join('');
    const ps = $('#profSel'), cur = ps.value || (T.engine.profile && T.engine.profile.id) || 'global';
    ps.innerHTML = T.allProfiles().map((p) => `<option value="${p.id}"${p.id === cur ? ' selected' : ''}>${T.escapeHTML(p.name)}</option>`).join('');
    this.renderProfile();
    $('#macroJson').value = JSON.stringify(T.cfg.macros, null, 1);
    $('#userProfJson').value = T.cfg.userProfiles.length ? JSON.stringify(T.cfg.userProfiles, null, 2) : '';
    $('#cfgJson').value = JSON.stringify(T.cfg);
    $('#midiCh').value = T.cfg.midi.ch; $('#midiCC').value = T.cfg.midi.faders.join(', '); $('#midiNotes').value = T.cfg.midi.pads.join(', ');
  },
  renderProfile() {
    const p = T.allProfiles().find((x) => x.id === $('#profSel').value) || T.PROFILES[0];
    const rows = p.buttons.map((b) => { const avail = !b.a || b.a.do !== 'key' || T.chord.pick(b.a.c) != null; return `<tr${avail ? '' : ' class="muted"'}><td>${T.escapeHTML(b.l)}</td><td class="num">${T.escapeHTML(b.a && b.a.do === 'key' ? (avail ? T.chord.pretty(b.a.c) : 'n/a on ' + T.targetOS()) : T.actions.describe(b.a))}</td><td class="muted">${b.g || ''}</td></tr>`; });
    const dials = (p.dials || []).map((d) => `<tr><td>⟳ ${T.escapeHTML(d.l)}</td><td class="num">${T.escapeHTML(T.actions.describe(d.cw))} / ${T.escapeHTML(T.actions.describe(d.ccw))}</td><td class="muted">dial</td></tr>`);
    const m = p.match || {}; const how = [m.exe && m.exe.length ? 'exe: ' + m.exe.slice(0, 4).join(', ') + (m.exe.length > 4 ? '…' : '') : '', m.title ? 'title ~ /' + m.title + '/' : ''].filter(Boolean).join(' · ') || 'fallback';
    $('#profTable').innerHTML = `<tr><th>Button</th><th>${T.escapeHTML(T.targetOS())} shortcut</th><th>group</th></tr>` + rows.join('') + dials.join('') + `<tr><td colspan="3" class="muted small">matches ${T.escapeHTML(how)} · workspace ${p.ws}</td></tr>`;
  },

  /* ---------------- TRIBUNAL ---------------- */
  tribunal() {
    $('#btnArm').addEventListener('click', async () => {
      if (T.host.armed) { await T.call('hostArm', { on: false }); return; }
      const g = T.tribunal.gate(); if (!g.open) { this.toast('Gate closed: ' + g.why, 'bad'); this.renderTribunal(); return; }
      const r = await T.call('hostArm', { on: true, gate: g.report }); if (!r || !r.ok) this.toast('Host refused to arm: ' + ((r && r.err) || '?'), 'bad');
    });
    $('#btnPanic').addEventListener('click', () => { T.call('panic', { reason: 'console PANIC' }); if (!T.link.isLeader()) T.host.panicDirect('console PANIC'); });
    $('#btnRerun').addEventListener('click', () => this.renderTribunal());
    $('#optStrict').addEventListener('change', (e) => T.call('patchCfg', { patch: { tribunal: { strict: e.target.checked } } }).then(() => this.renderTribunal()));
    $('#critics').addEventListener('change', (e) => { const cb = e.target.closest('input[data-ack]'); if (cb) { T.tribunal.ack(cb.dataset.ack, cb.checked); setTimeout(() => this.renderTribunal(), 150); } });
  },
  renderTribunal() {
    const out = T.tribunal.run(), g = T.tribunal.gate();
    $('#gateState').textContent = g.open ? 'GATE OPEN' : 'GATE CLOSED'; $('#gateState').className = 'state ' + (g.open ? 'open' : 'closed');
    $('#gateWhy').textContent = g.open ? (T.host.armed ? 'Armed.' : 'All critics satisfied — arming is allowed.') : g.why;
    $('#btnArm').textContent = T.host.armed ? 'Disarm' : 'Arm OS injection'; $('#btnArm').disabled = !T.host.connected || (!g.open && !T.host.armed);
    $('#optStrict').checked = T.cfg.tribunal.strict;
    $('#critics').innerHTML = out.map((c) => `<div class="panel critic ${c.v}"><div class="hd"><h2>${c.name}<span class="muted" style="font-family:var(--font-ui);letter-spacing:.04em;font-size:12px;margin-left:8px">${c.role}</span></h2><span class="pill ${c.v}">${c.v}${c.acked ? ' · ACK' : ''}</span></div>
      <ul>${c.notes.map((n) => `<li><span class="pill ${n[0]}" style="font-size:9.5px;padding:2px 5px;margin-right:6px">${n[0]}</span>${T.escapeHTML(n[1])}${n[2] ? `<span class="fix">→ ${T.escapeHTML(n[2])}</span>` : ''}</li>`).join('')}</ul>
      ${c.v === 'WARN' ? `<label class="chk" style="margin-top:8px"><input type="checkbox" data-ack="${c.id}"${c.acked ? ' checked' : ''}>I accept this residual risk</label>` : ''}</div>`).join('');
    this._trib = Date.now();
  },

  /* ---------------- DOSSIER ---------------- */
  dossier() {
    const D = T.DOSSIER, e = T.escapeHTML;
    $('#lineage').innerHTML = D.lineage.map((l) => `<article><div class="yr">${l.y}</div><h3>${e(l.n)}</h3><p>${e(l.who)} — ${e(l.how)}</p><p class="num">${e(l.num)}</p><p class="use">→ ${e(l.use)}</p><p><a href="${l.src}" target="_blank" rel="noopener">source</a></p></article>`).join('');
    $('#numbers').innerHTML = '<tr><th>Quantity</th><th>Value</th><th>Source</th></tr>' + D.numbers.map((n) => `<tr><td>${e(n[0])}</td><td class="num">${e(n[1])}</td><td class="muted">${e(n[2])}</td></tr>`).join('');
    $('#decisions').innerHTML = '<tr><th>Because</th><th>TABULA does</th></tr>' + D.decisions.map((d) => `<tr><td>${e(d[0])}</td><td>${e(d[1])}</td></tr>`).join('');
    $('#products').innerHTML = D.products.map((p) => `<tr><td><a href="${p[2]}" target="_blank" rel="noopener">${e(p[0])}</a></td><td class="muted">${e(p[1])}</td></tr>`).join('');
    $('#sources').innerHTML = D.sources.map((s) => `<li><a href="${s[1]}" target="_blank" rel="noopener">${e(s[0])}</a></li>`).join('');
  },

  /* ---------------- LINK ---------------- */
  linkTab() {
    $('#hostSeg').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const tok = $('#hostTok').value.trim();
      if (tok && !tok.startsWith('(') && !T.setRunToken(tok)) { this.toast('That does not look like a host token (43 letters, digits, - and _).', 'warn'); return; }   // pairing: kept in this tab only
      T.call('hostMode', { mode: b.dataset.m, url: $('#hostUrl').value.trim(), run: T.runToken });
    });
    const sense = (msg) => T.call('hostRequest', { msg, timeout: 10000 }).then((r) => this.toast(r && r.ok ? 'Host: ' + (r.msg || 'ok') : 'Host: ' + ((r && r.err) || 'no answer'), r && r.ok ? 'ok' : 'warn'));
    $('#senseStart').addEventListener('click', () => sense({ t: 'sense', op: 'start', source: $('#senseSrc').value, tangibles: +$('#tangCam').value, desk: { w: T.cfg.desk.w, h: T.cfg.desk.h } }));
    $('#senseStop').addEventListener('click', () => sense({ t: 'sense', op: 'stop' }));
    $('#senseBg').addEventListener('click', () => sense({ t: 'sense', op: 'background' }));
    $('#senseTap').addEventListener('click', () => { sense({ t: 'sense', op: 'tapcal' }); this.toast('Touch each ring on the desk and hold still for half a second', 'ok'); });
    $('#senseGc').addEventListener('click', () => sense({ t: 'sense', op: 'graycode', cam: Math.max(0, +$('#tangCam').value), texW: T.render.texW, texH: T.render.texH, step: T.cfg.calib.step, settle: T.cfg.calib.settleMs / 1000 }));
    $('#btnScreens').addEventListener('click', async () => {
      if (!('getScreenDetails' in window)) { this.toast('Window Management API not available in this browser/frame (Chrome/Edge on localhost supports it)', 'warn'); return; }
      try { const sd = await window.getScreenDetails(); this.screens = sd.screens.map((s) => `${s.label || 'screen'} · ${s.width}×${s.height}${s.isPrimary ? ' · primary' : ''}${s.isInternal ? ' · internal' : ''}`); } catch (e) { this.toast('Screen details refused: ' + e.message, 'warn'); }
    });
  },
  renderLink() {
    const h = T.host, i = h.info || {};
    for (const b of $$('#hostSeg button')) b.setAttribute('aria-pressed', String(b.dataset.m === h.mode));
    const urlV = T.cfg.host.url || (T.BOOT ? location.host : ''), tokV = T.runToken ? `(from the host link · ${T.runToken.slice(0, 4)}…)` : '';
    if (urlV !== this._urlV && document.activeElement !== $('#hostUrl')) { this._urlV = urlV; $('#hostUrl').value = urlV; }     // only when the value changed:
    if (tokV !== this._tokV && document.activeElement !== $('#hostTok')) { this._tokV = tokV; $('#hostTok').value = tokV; }     // never wipe what is being typed
    const rows = [['state', h.mode === 'off' ? 'off' : h.connected ? 'connected' : 'connecting…'], ['armed', h.armed ? 'YES' : 'no'], ['os', i.os || '—'], ['input', (i.input || '—') + (i.dry ? ' (dry-run)' : '')], ['focus', i.focus || '—'], ['capture', i.capture || '—'], ['sensing', i.sense || '—'], ['vlm', i.vlm ? `${i.vlm.provider} · ${i.vlm.model}${i.vlm.cloud ? ' (cloud)' : ''}` : '—'], ['caps', (i.caps || []).join(' ') || '—'], ['round trip', h.rtt != null ? h.rtt.toFixed(1) + ' ms' : '—']];
    if (h.audit) rows.push(['bind', h.audit.bind + (h.audit.lan ? ' (LAN)' : '')], ['token', h.audit.tokenLen ? h.audit.tokenLen + ' chars' + (h.audit.tokenDelivery ? ' · ' + h.audit.tokenDelivery : '') : '—'], ['origins', h.audit.origins || '—'], ['input', h.audit.inputBinding || '—']);
    const html = rows.map(([k, v]) => `<dt>${k}</dt><dd>${T.escapeHTML(String(v))}</dd>`).join('');
    if (html !== this._hs) { $('#hostStats').innerHTML = html; this._hs = html; }
    const s = i.senseStatus;
    $('#senseStats').innerHTML = s ? Object.entries(s).map(([k, v]) => `<dt>${T.escapeHTML(k)}</dt><dd>${T.escapeHTML(typeof v === 'object' ? JSON.stringify(v) : String(v))}</dd>`).join('') : '<dt>status</dt><dd>idle</dd>';
    const peers = [...T.link.peers.entries()].map(([id, p]) => [id, p.role]);
    const pr = [['this window', `${T.link.role} · ${T.link.isLeader() ? 'leader' : 'follower'}`], ['other windows', peers.length ? peers.map((p) => p[1]).join(', ') : 'none'], ['warp', T.warp.ok ? 'WebGL2' : T.warp.canvas ? '2D fallback' : 'not started']];
    if (this.screens) this.screens.forEach((s, k) => pr.push(['screen ' + (k + 1), s]));
    $('#peerStats').innerHTML = pr.map(([k, v]) => `<dt>${k}</dt><dd>${T.escapeHTML(v)}</dd>`).join('');
  },

  /* ---------------- inspector ---------------- */
  inspector() {
    const log = $('#log');
    const add = (e) => { const d = document.createElement('div'); d.className = e.level; const t = new Date(e.t); d.innerHTML = `<time>${t.toTimeString().slice(0, 8)}</time>${T.escapeHTML(e.src)} · ${T.escapeHTML(e.msg)}`; log.appendChild(d); while (log.childNodes.length > 300) log.removeChild(log.firstChild); log.scrollTop = log.scrollHeight; };
    T.log.buf.forEach(add); T.bus.on('log', add);
  },
  syncControls() {
    $('#optGrid').checked = !!T.cfg.output.grid; $('#pinGrid').checked = !!T.cfg.output.grid; $('#optHand').checked = !!T.cfg.input.simHand; $('#optKb').checked = !!T.cfg.desk.kb.on;
    for (const b of $$('#handSeg button')) b.setAttribute('aria-pressed', String(b.dataset.h === T.cfg.desk.handed));
    for (const b of $$('#airSeg button')) b.setAttribute('aria-pressed', String(b.dataset.m === T.cfg.input.air));
    $('#pinFlipX').checked = T.cfg.output.flipX; $('#pinFlipY').checked = T.cfg.output.flipY; $('#pinMesh').checked = T.cfg.output.mesh.on;
    $('#outRes').value = T.cfg.output.res.join('x'); $('#outGain').value = T.cfg.output.gain; $('#outFeather').value = T.cfg.output.feather;
    $('#tintR').value = T.cfg.output.tint[0]; $('#tintG').value = T.cfg.output.tint[1]; $('#tintB').value = T.cfg.output.tint[2];
    $('#optDim').checked = T.cfg.output.dimHands; $('#optHead').checked = T.cfg.output.headGuard; $('#gcSettle').value = T.cfg.calib.settleMs; $('#gcStep').value = String(T.cfg.calib.step);
  },
  refresh() {
    this.chips();
    for (const b of $$('#wsSeg button')) b.setAttribute('aria-pressed', String(b.dataset.ws === 'AUTO' ? T.engine.auto : b.dataset.ws === T.engine.ws));
    const cs = T.link.isLeader() ? [...T.input.contacts.values()].map((c) => ({ key: c.key, src: c.src, x: c.x, y: c.y })) : (T.link.remote ? T.link.remote.contacts : []);
    const txt = cs.length ? cs.map((c) => `${c.key.padEnd(10)} ${c.x.toFixed(1).padStart(6)} ${c.y.toFixed(1).padStart(6)} mm`).join('\n') : 'no contacts';
    const el = $('#contactList'); if (el.textContent !== txt) { el.textContent = txt; el.style.whiteSpace = 'pre'; }
    if (this.tab === 'link') this.renderLink();
    if (this.tab === 'tribunal' && Date.now() - (this._trib || 0) > 2000 && !(document.activeElement && document.activeElement.closest && document.activeElement.closest('#critics'))) this.renderTribunal();
    const air = $('#airRun'); if (air) air.textContent = T.air.on ? 'Stop AIR' : 'Start AIR';
  },
};
