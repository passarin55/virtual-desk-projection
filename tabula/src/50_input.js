/* ==========================================================================
   TABULA-Ω · input — one hub for every sensing path:
     sim   : mouse / touchscreen / pen on the console preview or projector view
     air   : webcam + MediaPipe Hand Landmarker (pinch or dwell = press)
     host  : depth-camera touch engine / IR light plane / TUIO via tabula_host.py
   All sources report desk millimetres; the hub filters (One Euro), removes the
   measured systematic bias, predicts ahead for rendering, and dispatches.
   ========================================================================== */
'use strict';

T.input = {
  contacts: new Map(),   // key → contact (pressed)
  hovers: new Map(),     // key → hover point (not pressed)
  hands: [],             // hand/arm silhouettes (desk-mm polygons) for occlusion + light masking
  heads: [],             // head discs from host depth (projector-glare guard)
  lastSeen: 0,
  /* raw event from a source. phase: 'down' | 'move' | 'up' | 'hover' | 'leave' */
  ev(src, id, phase, x, y, extra = {}) {
    const key = src + ':' + id, now = T.now(), tS = now / 1000;
    const bias = (T.cfg.input.bias && T.cfg.input.bias[src]) || [0, 0];
    const filt = src === 'air' || src === 'host';
    if (phase === 'hover' || phase === 'leave') {
      if (phase === 'leave') { this.hovers.delete(key); return; }
      let h = this.hovers.get(key);
      if (!h) { h = { key, src, id, f: filt ? new T.OneEuro2(T.cfg.input.euro) : null }; this.hovers.set(key, h); }
      const p = h.f ? h.f.filter(x, y, tS) : [x, y];
      h.x = p[0] + bias[0]; h.y = p[1] + bias[1]; h.t = now; h.z = extra.z; h.dwell = extra.dwell || 0;
      return;
    }
    let c = this.contacts.get(key);
    if (phase === 'down') {
      if (c) this.ev(src, id, 'up', c.rx, c.ry);
      this.hovers.delete(key);
      c = { key, src, id, x: x + bias[0], y: y + bias[1], rx: x, ry: y, x0: x + bias[0], y0: y + bias[1], t0: now, t: now, vx: 0, vy: 0, maxD: 0, path: [], widget: null, data: {}, pressure: extra.pressure ?? 0.5, kind: extra.kind || 'finger', f: filt ? new T.OneEuro2(T.cfg.input.euro) : null };
      if (c.f) c.f.filter(x, y, tS);
      this.contacts.set(key, c);
      c.path.push([c.x, c.y, now]);
      T.engine.contactDown(c);
      this.lastSeen = now;
      return;
    }
    if (!c) return;
    if (phase === 'move') {
      const p = c.f ? c.f.filter(x, y, tS) : [x, y];
      const nx = p[0] + bias[0], ny = p[1] + bias[1], dt = Math.max(1, now - c.t);
      c.vx = T.lerp(c.vx, ((nx - c.x) / dt) * 1000, 0.5); c.vy = T.lerp(c.vy, ((ny - c.y) / dt) * 1000, 0.5);
      c.px = c.x; c.py = c.y; c.x = nx; c.y = ny; c.rx = x; c.ry = y; c.t = now; c.pressure = extra.pressure ?? c.pressure;
      c.maxD = Math.max(c.maxD, T.dist(c.x, c.y, c.x0, c.y0));
      c.path.push([c.x, c.y, now]); if (c.path.length > 90) c.path.shift();
      T.engine.contactMove(c);
      this.lastSeen = now;
      return;
    }
    if (phase === 'up' || phase === 'cancel') {
      c.t = now; c.dur = now - c.t0; c.cancelled = phase === 'cancel';
      this.contacts.delete(key);
      T.engine.contactUp(c);
      T.bus.emit('input:up', c);
    }
  },
  /* predicted position (ms ahead) for drawing only — hides part of the pipeline latency on drags */
  predict(c) { const ms = T.cfg.input.predictMs || 0; return ms && c.src !== 'sim' ? [c.x + c.vx * ms / 1000, c.y + c.vy * ms / 1000] : [c.x, c.y]; },
  count() { return this.contacts.size; },
  releaseAll(src) { for (const c of [...this.contacts.values()]) if (!src || c.src === src) this.ev(c.src, c.id, 'cancel', c.rx, c.ry); },
};

/* ---------------- simulated hand silhouette (for occlusion-aware callouts + light masking demo) ---------------- */
/* A hand pointing with the INDEX finger, seen from above as the camera and projector see it: the extended finger sits on
   the thumb side of the fist, the thumb lies along it, and the middle, ring and little fingers are curled (three knuckle
   bumps). Outline in mm, for a right hand: a = from the fingertip back toward the elbow, b = across, + toward the thumb. */
T.input.HAND_OUTLINE = [
  [-1.5, -6], [-3.5, -2.5], [-3.5, 2.5], [-1.5, 6],                             // fingertip (the touch point is a = 0)
  [4, 9], [22, 9.8], [44, 10.6], [56, 11.6],                                    // index finger, thumb side
  [50, 14.5], [46.5, 18.5], [46.5, 23.5], [50, 27.5], [57, 30.5],               // thumb tip, resting along the index finger
  [74, 36], [95, 40], [118, 40], [138, 35], [158, 30],                          // thumb and ball of the thumb → wrist
  [1000, 32], [1000, -44],                                                      // forearm
  [158, -44], [130, -54], [100, -61], [84, -63],                                // wrist → little-finger edge of the hand
  [74, -62], [67, -58], [64, -51], [66, -46],                                   // little finger, curled
  [61, -42], [59, -36], [61, -30],                                              // ring finger, curled
  [57, -26], [56, -19], [58, -13],                                              // middle finger, curled
  [50, -10.6], [30, -10], [10, -9], [2, -8],                                    // index finger, other side
];
T.input.simHandPoly = (x, y, handed) => {
  const H = T.cfg.desk.h, W = T.cfg.desk.w;
  const sgn = handed === 'left' ? -1 : 1;                                       // a left hand is the mirror image
  // forearm enters from the near edge, offset toward the handed side
  const ex = T.clamp(x + sgn * 170, -60, W + 60), ey = H + 80;
  const ang = Math.atan2(ey - y, ex - x), ux = Math.cos(ang), uy = Math.sin(ang), nx = -uy, ny = ux;
  return T.input.HAND_OUTLINE.map(([a, b]) => [x + ux * a + nx * b * sgn, y + uy * a + ny * b * sgn]);
};

/* ---------------- sim pointer source (mouse / touch / pen on a canvas) ---------------- */
T.SimPointer = class {
  /* toDesk(clientX, clientY) → [xmm, ymm] ; forward(phase,id,x,y,extra) where to deliver */
  constructor(el, toDesk, forward) {
    this.el = el; this.toDesk = toDesk; this.fwd = forward; this.active = new Map(); this.pinned = new Map(); this.twin = null;
    el.addEventListener('pointerdown', (e) => this.down(e));
    el.addEventListener('pointermove', (e) => this.move(e));
    el.addEventListener('pointerup', (e) => this.up(e));
    el.addEventListener('pointercancel', (e) => this.up(e, true));
    el.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse' && !this.active.size) this.fwd('leave', 'm', 0, 0); });
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  id(e) { return e.pointerType === 'mouse' ? 'm' : e.pointerType[0] + e.pointerId; }
  down(e) {
    if (e.button === 2) return;
    const [x, y] = this.toDesk(e.clientX, e.clientY); if (x == null) return;
    e.preventDefault(); try { this.el.setPointerCapture(e.pointerId); } catch (_) { /* ok */ }
    const id = this.id(e);
    // Shift+click: pin / unpin a stationary finger (lets a mouse do real multi-touch)
    if (e.shiftKey && e.pointerType === 'mouse') {
      for (const [pid, p] of this.pinned) if (T.dist(p[0], p[1], x, y) < 12) { this.pinned.delete(pid); this.fwd('up', pid, p[0], p[1]); return; }
      const pid = 'pin' + (this.pinned.size + 1) + '_' + ((Math.random() * 1e4) | 0); this.pinned.set(pid, [x, y]); this.fwd('down', pid, x, y); return;
    }
    const extra = { pressure: e.pressure || 0.5, kind: e.pointerType === 'pen' ? 'pen' : 'finger' };
    this.active.set(e.pointerId, { id, x0: x, y0: y });
    this.fwd('down', id, x, y, extra);
    // Alt: mirrored twin (pinch / rotate). Ctrl/⌘: parallel twin (two-finger drag). Ctrl+Alt: three parallel fingers.
    if (e.pointerType === 'mouse' && (e.altKey || e.ctrlKey || e.metaKey)) {
      const par = e.ctrlKey || e.metaKey, three = par && e.altKey;
      this.twin = { par, three, cx: x + (par ? 0 : 40), cy: y, x0: x, y0: y };
      if (par) { this.fwd('down', 'tw1', x + 22, y); if (three) this.fwd('down', 'tw2', x + 44, y); }
      else this.fwd('down', 'tw1', 2 * this.twin.cx - x, 2 * this.twin.cy - y);
    }
  }
  move(e) {
    const [x, y] = this.toDesk(e.clientX, e.clientY); if (x == null) return;
    const a = this.active.get(e.pointerId);
    if (!a) { if (e.pointerType !== 'touch') this.fwd('hover', this.id(e), x, y); return; }
    this.fwd('move', a.id, x, y, { pressure: e.pressure || 0.5 });
    if (this.twin && e.pointerType === 'mouse') {
      const t = this.twin;
      if (t.par) { this.fwd('move', 'tw1', x + 22, y); if (t.three) this.fwd('move', 'tw2', x + 44, y); }
      else this.fwd('move', 'tw1', 2 * t.cx - x, 2 * t.cy - y);
    }
  }
  up(e, cancel) {
    const a = this.active.get(e.pointerId); if (!a) return;
    const [x, y] = this.toDesk(e.clientX, e.clientY);
    this.active.delete(e.pointerId);
    this.fwd(cancel ? 'cancel' : 'up', a.id, x ?? a.x0, y ?? a.y0);
    if (this.twin && e.pointerType === 'mouse') { this.fwd('up', 'tw1', 0, 0); if (this.twin.three) this.fwd('up', 'tw2', 0, 0); this.twin = null; }
  }
};

/* ---------------- AIR source: webcam + MediaPipe Hand Landmarker ---------------- */
T.air = {
  on: false, video: null, lm: null, stream: null, lastTs: -1, hands: [], fps: 0, _fc: 0, _ft: 0, err: null,
  MP_VER: '1.0.1',
  modelUrl() { return (T.BOOT && T.BOOT.handModel) || 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'; },
  async start(deviceId) {
    if (this.on) return true;
    this.err = null;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: Object.assign({ width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 60 } }, deviceId ? { deviceId: { exact: deviceId } } : {}) });
    } catch (e) { this.err = 'camera refused: ' + e.message; T.log.warn('air', this.err); return false; }
    this.video = document.createElement('video'); this.video.muted = true; this.video.playsInline = true; this.video.srcObject = this.stream; await this.video.play();
    try {
      const base = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${this.MP_VER}`;
      const vision = await import(/* @vite-ignore */ base + '/vision_bundle.mjs');
      const fs = await vision.FilesetResolver.forVisionTasks(base + '/wasm');
      this.lm = await vision.HandLandmarker.createFromOptions(fs, { baseOptions: { modelAssetPath: this.modelUrl(), delegate: 'GPU' }, runningMode: 'VIDEO', numHands: 2, minHandDetectionConfidence: 0.5, minTrackingConfidence: 0.5 });
    } catch (e) { this.err = 'MediaPipe failed to load: ' + e.message; T.log.warn('air', this.err + ' — AIR mode needs network access to jsdelivr + the model URL (or serve the model from the host).'); this.stop(); return false; }
    this.on = true; T.log.info('air', 'AIR hand tracking live (' + this.video.videoWidth + '×' + this.video.videoHeight + ')');
    return true;
  },
  stop() { this.on = false; if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; this.hands = []; T.input.releaseAll('air'); for (const k of [...T.input.hovers.keys()]) if (k.startsWith('air:')) T.input.hovers.delete(k); },
  /* camera px → desk mm via the calibrated homography (normalised camera coords) */
  toDesk(u, v) { return T.calib.camToDesk(u, v); },
  poll(now) {
    if (!this.on || !this.lm || !this.video || this.video.readyState < 2) return;
    const ts = this.video.currentTime; if (ts === this.lastTs) return; this.lastTs = ts;
    let res; try { res = this.lm.detectForVideo(this.video, now); } catch (e) { return; }
    this._fc++; if (now - this._ft > 1000) { this.fps = this._fc; this._fc = 0; this._ft = now; }
    const seen = new Set(); this.hands = [];
    (res.landmarks || []).forEach((L, hi) => {
      const id = 'h' + hi; seen.add(id);
      const P = (i) => this.toDesk(L[i].x, L[i].y);
      const tip = P(8), th = P(4), wr = P(0), mcp = P(5); if (!tip || !th || !wr || !mcp) return;
      const cur = [(tip[0] + th[0]) / 2, (tip[1] + th[1]) / 2];
      const scale = T.dist(wr[0], wr[1], mcp[0], mcp[1]) || 1, pinch = T.dist(tip[0], tip[1], th[0], th[1]) / scale;
      const poly = T.geom.convexHull(L.map((_, i) => P(i)).filter(Boolean));
      this.hands.push(poly);
      const key = 'air:' + id, pressed = T.input.contacts.has(key);
      let down;
      if (T.cfg.input.air === 'dwell') {
        const h = T.input.hovers.get(key);
        const still = h && T.dist(h.x, h.y, cur[0], cur[1]) < 5;
        const dwell = still ? (h.dwell || 0) + Math.min(100, now - h.t) : 0;
        down = pressed ? (T.dist(T.input.contacts.get(key).x, T.input.contacts.get(key).y, cur[0], cur[1]) < 14 && (now - T.input.contacts.get(key).t0) < 180) : dwell > T.cfg.input.dwellMs;
        if (!pressed) T.input.ev('air', id, 'hover', cur[0], cur[1], { dwell });
      } else {
        down = pressed ? pinch < 0.35 : pinch < 0.25;           // hysteresis
      }
      if (down && !pressed) T.input.ev('air', id, 'down', cur[0], cur[1]);
      else if (down) T.input.ev('air', id, 'move', cur[0], cur[1]);
      else { if (pressed) T.input.ev('air', id, 'up', cur[0], cur[1]); if (T.cfg.input.air !== 'dwell') T.input.ev('air', id, 'hover', cur[0], cur[1]); }
    });
    for (const k of [...T.input.contacts.keys()]) if (k.startsWith('air:') && !seen.has(k.slice(4))) { const c = T.input.contacts.get(k); T.input.ev('air', c.id, 'up', c.rx, c.ry); }
    for (const k of [...T.input.hovers.keys()]) if (k.startsWith('air:') && !seen.has(k.slice(4))) T.input.hovers.delete(k);
  },
};

/* ---------------- HOST source: depth / IR / TUIO contacts arrive as normalised desk coords ---------------- */
T.bus.on('host:touches', (m) => {
  const W = T.cfg.desk.w, H = T.cfg.desk.h, seen = new Set();
  for (const c of m.contacts || []) {
    const id = (m.src || 'h') + c.id; seen.add('host:' + id);
    const x = c.x * W, y = c.y * H;
    if (c.phase === 'hover') { T.input.ev('host', id, 'hover', x, y, { z: c.z }); continue; }
    const key = 'host:' + id, has = T.input.contacts.has(key);
    if (c.phase === 'up') { if (has) T.input.ev('host', id, 'up', x, y); continue; }
    T.input.ev('host', id, has ? 'move' : 'down', x, y, { pressure: c.p ?? 0.5 });
  }
  for (const [k, c] of [...T.input.contacts]) if (k.startsWith('host:') && !seen.has(k)) T.input.ev('host', c.id, 'up', c.rx, c.ry);
  for (const k of [...T.input.hovers.keys()]) if (k.startsWith('host:') && !seen.has(k)) T.input.hovers.delete(k);
  T.input.hostHands = (m.hands || []).map((poly) => poly.map((p) => [p[0] * W, p[1] * H]));
  T.input.heads = (m.heads || []).map((h) => ({ x: h.x * W, y: h.y * H, r: (h.r || 0.12) * W }));
  if (m.objects) T.engine.setHostObjects(m.objects.map((o) => Object.assign({}, o, { x: o.x * W, y: o.y * H, w: (o.w || 0) * W, h: (o.h || 0) * H })));
  if (m.palm) T.host.panic('flat palm on desk');
});
