/* ==========================================================================
   TABULA-Ω · calibration
   • Gray-code structured light (MSB→LSB, each bit + inverse, black/white refs)
     decoded per camera pixel → one correspondence per stripe cell → RANSAC
     homography camera → desk mm. Works with a real webcam or SIM CAM (a
     synthetic perspective camera with lens distortion + noise, so the solver
     can be exercised and scored against ground truth without hardware).
   • Touch-accuracy test (9 targets): measures systematic offset (removed
     automatically) and spread → the minimum safe target size.
   • Latency probe: projector→camera round trip with a flashed square.
   ========================================================================== */
'use strict';

T.bus.on('host:gc', (m) => {
  if (m.op === 'show') {
    const plan = T.gray.plan(T.render.texW, T.render.texH, m.step || 16);
    T.calib.pattern = { plan, pat: plan.pats[m.k] }; T.engine.dirty = true;
    T.bus.emit('calib:progress', { k: m.k, n: m.n || plan.pats.length });
    requestAnimationFrame(() => requestAnimationFrame(() => T.host.send({ t: 'gc', op: 'shown', k: m.k })));
  } else if (m.op === 'clear') { T.calib.pattern = null; T.engine.dirty = true; }
  else if (m.op === 'done') { T.calib.pattern = null; T.bus.emit('toast', { text: m.ok ? `Host camera calibrated · ${m.inliers}/${m.cells} cells · ${m.rmsMm.toFixed(2)} mm RMS` : 'Host Gray-code failed: ' + m.err, kind: m.ok ? 'ok' : 'warn' }); }
});
T.bus.on('host:tapcal', (m) => {
  if (m.op === 'target') T.calib.hostTarget = { x: m.x * T.cfg.desk.w, y: m.y * T.cfg.desk.h, i: m.i, n: m.n };
  else if (m.op === 'done') { T.calib.hostTarget = null; T.bus.emit('toast', { text: m.ok ? `Sensor → desk calibrated from ${m.n} touches · ${m.rmsMm.toFixed(1)} mm RMS` : 'Tap calibration failed: ' + m.err, kind: m.ok ? 'ok' : 'warn' }); }
  T.engine.dirty = true;
});

T.calib = {
  pattern: null, flash: null, flashRect: null, showGrid: false, running: false, cancel: false, last: null, cam: null, camStream: null,

  /* ---------- one-parameter radial lens model on normalised camera coords (a = width/height) ---------- */
  dist: {
    undist(u, v, k1, a) { const x = (u - 0.5) * a, y = v - 0.5, R2 = (a * a + 1) / 4, f = 1 + k1 * (x * x + y * y) / R2; return [0.5 + x * f / a, 0.5 + y * f]; },
    dist(u, v, k1, a) { const xu = (u - 0.5) * a, yu = v - 0.5, R2 = (a * a + 1) / 4; let x = xu, y = yu; for (let i = 0; i < 10; i++) { const f = 1 + k1 * (x * x + y * y) / R2; x = xu / f; y = yu / f; } return [0.5 + x / a, 0.5 + y]; },
  },
  /* normalised camera (0..1) → desk mm, and back — every camera consumer goes through these */
  camToDesk(u, v) { const c = T.cfg.calib; if (!c.H_desk_cam) return null; const p = c.k1 ? this.dist.undist(u, v, c.k1, c.aspect || 16 / 9) : [u, v]; return T.m3.apply(c.H_desk_cam, p[0], p[1]); },
  deskToCam(x, y) { const c = T.cfg.calib; const Hi = c.H_desk_cam && T.m3.inv(c.H_desk_cam); if (!Hi) return null; const p = T.m3.apply(Hi, x, y); return c.k1 ? this.dist.dist(p[0], p[1], c.k1, c.aspect || 16 / 9) : p; },
  /* fit k1 by golden-section search: undistort camera points, refit the homography, minimise RMS */
  fitK1(camN, surf, a, idx) {
    const pts = idx.map((i) => camN[i]), dst = idx.map((i) => surf[i]);
    const cost = (k) => { const u = pts.map((p) => this.dist.undist(p[0], p[1], k, a)); const H = T.geom.dlt(u, dst); return H ? T.geom.rms(H, u, dst) : Infinity; };
    let lo = -0.4, hi = 0.4; const g = (Math.sqrt(5) - 1) / 2;
    let c = hi - g * (hi - lo), d = lo + g * (hi - lo), fc = cost(c), fd = cost(d);
    for (let it = 0; it < 32; it++) { if (fc < fd) { hi = d; d = c; fd = fc; c = hi - g * (hi - lo); fc = cost(c); } else { lo = c; c = d; fc = fd; d = lo + g * (hi - lo); fd = cost(d); } }
    const k = (lo + hi) / 2; return { k1: k, rms: cost(k), rms0: cost(0) };
  },

  /* ---------- SIM CAM: plausible camera looking down at the desk ---------- */
  simTruth(camW, camH) {
    const s = T.cfg.calib.sim, W = T.cfg.desk.w, H = T.cfg.desk.h;
    const yaw = s.yaw * Math.PI / 180, pitch = s.pitch / 100;
    const cx = camW / 2, cy = camH / 2, sc = Math.min(camW * 0.82 / W, camH * 0.82 / H);
    // desk corners → camera: scale, keystone from pitch (far edge narrower), yaw rotation
    const quad = [[0, 0], [W, 0], [W, H], [0, H]].map(([x, y]) => {
      const nx = (x - W / 2) * sc, ny = (y - H / 2) * sc, k = 1 - pitch * (0.5 - y / H);
      const px = nx * k, py = ny * (1 + pitch * 0.15);
      return [cx + px * Math.cos(yaw) - py * Math.sin(yaw), cy + px * Math.sin(yaw) + py * Math.cos(yaw)];
    });
    return { Hcam_desk: T.geom.dlt([[0, 0], [W, 0], [W, H], [0, H]], quad), k1: s.k1, cx, cy, rn: Math.hypot(camW, camH) / 2 };
  },
  simGrab(truth, camW, camH, rng) {
    const S = T.render.sctx.getImageData(0, 0, T.render.texW, T.render.texH).data, tw = T.render.texW, th = T.render.texH, sPx = tw / T.cfg.desk.w;
    const Hi = T.m3.inv(truth.Hcam_desk), out = new Float32Array(camW * camH), amb = T.cfg.calib.sim.ambient, noise = T.cfg.calib.sim.noise;
    for (let y = 0; y < camH; y++) for (let x = 0; x < camW; x++) {
      const dx = (x + 0.5 - truth.cx) / truth.rn, dy = (y + 0.5 - truth.cy) / truth.rn, r2 = dx * dx + dy * dy, f = 1 + truth.k1 * r2;
      const ux = truth.cx + dx * truth.rn * f, uy = truth.cy + dy * truth.rn * f;           // ideal (undistorted) pixel
      const [mx, my] = T.m3.apply(Hi, ux, uy);
      let v = amb;
      const sx = Math.floor(mx * sPx), sy = Math.floor(my * sPx);
      if (sx >= 0 && sy >= 0 && sx < tw && sy < th) { const i = (sy * tw + sx) * 4; v += (0.2126 * S[i] + 0.7152 * S[i + 1] + 0.0722 * S[i + 2]) * 0.72 * (1 - 0.35 * r2); }
      out[y * camW + x] = v + (rng() - 0.5) * 2 * noise;
    }
    return out;
  },
  /* ---------- real camera ---------- */
  async openCam(deviceId) {
    if (T.air.on && T.air.video) return T.air.video;
    if (this.cam) return this.cam;
    const st = await navigator.mediaDevices.getUserMedia({ video: Object.assign({ width: { ideal: 1280 }, height: { ideal: 720 } }, deviceId ? { deviceId: { exact: deviceId } } : {}) });
    const tr = st.getVideoTracks()[0];
    try { const caps = tr.getCapabilities ? tr.getCapabilities() : {}; if (caps.exposureMode && caps.exposureMode.includes('manual')) { const hz = T.cfg.scheme.projHz || 60, ms = (T.cfg.scheme.mains === 50 && hz === 60) ? 50 : 2000 / hz; await tr.applyConstraints({ advanced: [{ exposureMode: 'manual', exposureTime: ms * 10 }] }); T.log.info('calib', `camera exposure locked at ${ms.toFixed(1)} ms (multiple of the projector frame)`); } } catch (e) { T.log.warn('calib', 'could not lock exposure: ' + e.message); }
    const v = document.createElement('video'); v.muted = true; v.playsInline = true; v.srcObject = st; await v.play();
    this.cam = v; this.camStream = st; return v;
  },
  closeCam() { if (this.camStream) this.camStream.getTracks().forEach((t) => t.stop()); this.cam = null; this.camStream = null; },
  grabVideo(video, camW, camH) {
    if (!this._c) this._c = document.createElement('canvas');
    const c = this._c; c.width = camW; c.height = camH; const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(video, 0, 0, camW, camH);
    const d = g.getImageData(0, 0, camW, camH).data, out = new Float32Array(camW * camH);
    for (let i = 0; i < out.length; i++) out[i] = 0.2126 * d[i * 4] + 0.7152 * d[i * 4 + 1] + 0.0722 * d[i * 4 + 2];
    return out;
  },
  raf() { return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); },

  /* ---------- Gray-code run ---------- */
  async runGray(opt = {}) {
    if (this.running) return { ok: false, err: 'already running' };
    this.running = true; this.cancel = false;
    const src = opt.src || 'sim', step = opt.step || T.cfg.calib.step, settle = opt.settleMs ?? T.cfg.calib.settleMs;
    let camW = 320, camH = 180, video = null, truth = null; const rng = T.rng(opt.seed || 7);
    try {
      if (src === 'webcam') { video = await this.openCam(opt.deviceId); const ar = video.videoHeight / video.videoWidth || 0.5625; camW = 480; camH = Math.round(480 * ar); }
      else truth = this.simTruth(camW, camH);
    } catch (e) { this.running = false; return { ok: false, err: 'camera: ' + e.message }; }
    const plan = T.gray.plan(T.render.texW, T.render.texH, step), frames = [];
    T.log.info('calib', `Gray-code: ${plan.pats.length} patterns (${plan.bx}+${plan.by} bits, ${step}px stripes) via ${src === 'sim' ? 'SIM CAM' : 'webcam'}`);
    const t0 = T.now();
    for (let k = 0; k < plan.pats.length; k++) {
      if (this.cancel) { this.pattern = null; this.running = false; return { ok: false, err: 'cancelled' }; }
      this.pattern = { plan, pat: plan.pats[k] };
      T.bus.emit('calib:progress', { k, n: plan.pats.length, pat: plan.pats[k] });
      await this.raf();
      if (src === 'webcam') { await T.sleep(settle); const a = this.grabVideo(video, camW, camH); await T.sleep(40); const b = this.grabVideo(video, camW, camH); for (let i = 0; i < a.length; i++) a[i] = (a[i] + b[i]) / 2; frames.push(a); }
      else { T.engine.drawSurface(T.render.sctx, T.render.texW, T.render.texH, T.now()); frames.push(this.simGrab(truth, camW, camH, rng)); }
    }
    this.pattern = null;
    const dec = T.gray.decode(plan, frames, camW, camH, { thrBlack: src === 'sim' ? 30 : 18, thrWhite: src === 'sim' ? 6 : 3 });
    const corr = T.gray.correspondences(plan, dec, camW, camH, 2);
    const res = { ok: false, src, plan: { n: plan.pats.length, step, bx: plan.bx, by: plan.by }, camW, camH, decoded: dec.ok, cells: corr.cam.length, ms: Math.round(T.now() - t0) };
    res.viz = this.viz(plan, dec, camW, camH);
    if (corr.cam.length < 12) { res.err = `only ${corr.cam.length} decodable cells — is the camera seeing the projection? (exposure, focus, room light)`; this.running = false; this.last = res; T.bus.emit('calib:done', res); return res; }
    // work in normalised camera coordinates so the result is independent of capture resolution
    const aspect = camW / camH, camN = corr.cam.map((p) => [p[0] / camW, p[1] / camH]);
    const thr = Math.max(3, step * 0.75);
    let rs = T.geom.ransac(camN, corr.surf, { thresh: thr, iters: 1500, rng: T.rng(11) });
    if (!rs) { res.err = 'RANSAC failed (degenerate correspondences)'; this.running = false; this.last = res; T.bus.emit('calib:done', res); return res; }
    // lens: estimate radial k1 on the inliers, then re-run RANSAC on undistorted points
    const kf = this.fitK1(camN, corr.surf, aspect, rs.inliers);
    let k1 = 0;
    if (kf.rms < kf.rms0 * 0.9) {
      k1 = kf.k1; const und = camN.map((p) => this.dist.undist(p[0], p[1], k1, aspect));
      const rs2 = T.geom.ransac(und, corr.surf, { thresh: thr, iters: 1500, rng: T.rng(13) }); if (rs2) rs = rs2; else k1 = 0;
    }
    const mmPerPx = T.cfg.desk.w / T.render.texW;
    const Hdesk_camn = T.m3.norm(T.m3.mul(T.m3.scale(mmPerPx, mmPerPx), rs.H));
    Object.assign(res, { ok: true, H: Hdesk_camn, k1, aspect, rms0: kf.rms0, inliers: rs.inliers.length, ratio: rs.ratio, rms: rs.rms, rmsMm: rs.rms * mmPerPx, cond: T.m3.cond(Hdesk_camn) });
    if (truth) { // ground truth error in mm over a grid inside the desk (true camera: homography, then radial distortion)
      let e = 0, n = 0; const W = T.cfg.desk.w, H = T.cfg.desk.h;
      const map = (u, v) => { const p = k1 ? this.dist.undist(u, v, k1, aspect) : [u, v]; return T.m3.apply(Hdesk_camn, p[0], p[1]); };
      for (let y = 0.1; y <= 0.9; y += 0.1) for (let x = 0.1; x <= 0.9; x += 0.1) {
        const [cxp, cyp] = T.m3.apply(truth.Hcam_desk, x * W, y * H);
        const dx = (cxp - truth.cx) / truth.rn, dy = (cyp - truth.cy) / truth.rn; let xd = dx, yd = dy;
        for (let it = 0; it < 8; it++) { const f = 1 + truth.k1 * (xd * xd + yd * yd); xd = dx / f; yd = dy / f; }
        const [mx, my] = map((truth.cx + xd * truth.rn) / camW, (truth.cy + yd * truth.rn) / camH);
        e += (mx - x * W) ** 2 + (my - y * H) ** 2; n++;
      }
      res.truthMm = Math.sqrt(e / n);
    }
    this.running = false; this.last = res;
    T.log.info('calib', `solved: ${res.inliers}/${res.cells} inliers, RMS ${res.rms.toFixed(2)} px = ${res.rmsMm.toFixed(2)} mm` + (res.truthMm != null ? `, ground truth ${res.truthMm.toFixed(2)} mm` : ''));
    T.bus.emit('calib:done', res);
    if (opt.apply !== false) this.apply(res);
    return res;
  },
  apply(res) {
    if (!res || !res.ok) return false;
    Object.assign(T.cfg.calib, { H_desk_cam: res.H, k1: res.k1 || 0, aspect: res.aspect || 16 / 9, rms: res.rms, rmsMm: res.rmsMm, method: res.src === 'sim' ? 'gray-code (SIM CAM)' : 'gray-code (webcam)', at: Date.now(), truthMm: res.truthMm ?? null });
    T.setCfgDirty(); return true;
  },
  viz(plan, dec, w, h) {
    const img = new Uint8ClampedArray(w * h * 4);
    for (let i = 0; i < w * h; i++) {
      if (!dec.valid[i]) { img[i * 4 + 3] = 255; continue; }
      const hue = dec.col[i] / plan.nx, lum = 0.25 + 0.6 * dec.row[i] / plan.ny;
      const k = (n) => (n + hue * 12) % 12, a = 0.9 * Math.min(lum, 1 - lum), f = (n) => lum - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
      img[i * 4] = f(0) * 255; img[i * 4 + 1] = f(8) * 255; img[i * 4 + 2] = f(4) * 255; img[i * 4 + 3] = 255;
    }
    return { w, h, data: img };
  },

  /* ---------- host-driven sessions: the host camera / depth sensor asks the page to project ---------- */
  hostTarget: null,
  drawHostTarget(G, now) {
    const t = this.hostTarget; if (!t) return; const p = 1 + 0.12 * Math.sin(now / 150);
    G.ring(t.x, t.y, 11 * p, T.PAL.ir, 1.4); G.ring(t.x, t.y, 3, T.PAL.ir, 0.9); G.line(t.x - 18, t.y, t.x + 18, t.y, T.PAL.ir, 0.5); G.line(t.x, t.y - 18, t.x, t.y + 18, T.PAL.ir, 0.5);
    G.text(`TOUCH AND HOLD · ${t.i + 1} / ${t.n}`, t.x, t.y - 19, { sz: T.TYPE.small, al: 'center', col: T.PAL.ir });
  },

  /* ---------- touch accuracy test ---------- */
  acc: {
    active: false, targets: [], i: 0, samples: [], rounds: 1, round: 0, t0: 0,
    start(rounds = 1) {
      const W = T.cfg.desk.w, H = T.cfg.desk.h;
      this.targets = []; for (const fy of [0.24, 0.55, 0.86]) for (const fx of [0.12, 0.5, 0.88]) this.targets.push([fx * W, fy * H]);
      this.i = 0; this.samples = []; this.rounds = rounds; this.round = 0; this.active = true; this.t0 = T.now();
      T.log.info('calib', 'accuracy test: tap the centre of each ring');
    },
    stop() { this.active = false; },
    tap(c) {
      const [tx, ty] = this.targets[this.i], b = (T.cfg.input.bias && T.cfg.input.bias[c.src]) || [0, 0];
      this.samples.push({ tx, ty, x: c.x - b[0], y: c.y - b[1], src: c.src });
      T.fx.ripple(c.x, c.y, T.PAL.amber, 10);
      this.i++; if (this.i >= this.targets.length) { this.i = 0; this.round++; if (this.round >= this.rounds) this.finish(); }
      T.bus.emit('calib:acc', { i: this.i, round: this.round, n: this.samples.length });
    },
    finish() {
      this.active = false; const S = this.samples; if (S.length < 3) return;
      const mx = S.reduce((s, p) => s + (p.x - p.tx), 0) / S.length, my = S.reduce((s, p) => s + (p.y - p.ty), 0) / S.length;
      const res = S.map((p) => [p.x - p.tx - mx, p.y - p.ty - my]);
      const sx = Math.sqrt(res.reduce((s, r) => s + r[0] * r[0], 0) / Math.max(1, S.length - 1)), sy = Math.sqrt(res.reduce((s, r) => s + r[1] * r[1], 0) / Math.max(1, S.length - 1));
      const radial = res.map((r) => Math.hypot(r[0], r[1])).sort((a, b) => a - b);
      const r95 = Math.max(2.4477 * Math.sqrt((sx * sx + sy * sy) / 2), radial[Math.min(radial.length - 1, Math.ceil(radial.length * 0.95) - 1)]);
      const src = S[S.length - 1].src, minTarget = Math.max(10, 2 * r95 + 2);
      T.cfg.calib.accuracy = { src, n: S.length, bias: [mx, my], sd: [sx, sy], r95, minTarget, at: Date.now() };
      T.cfg.input.bias[src] = [-mx, -my];
      T.setCfgDirty();
      T.log.info('calib', `accuracy (${src}): offset ${mx.toFixed(1)}, ${my.toFixed(1)} mm removed · spread R95 ${r95.toFixed(1)} mm → targets ≥ ${minTarget.toFixed(0)} mm`);
      T.bus.emit('calib:accdone', T.cfg.calib.accuracy);
    },
    draw(G, now) {
      const [x, y] = this.targets[this.i] || [0, 0], pulse = 1 + 0.12 * Math.sin(now / 160);
      G.ring(x, y, 10 * pulse, T.PAL.amber, 1.2); G.ring(x, y, 3, T.PAL.amber, 0.8); G.line(x - 16, y, x + 16, y, T.PAL.amber, 0.5); G.line(x, y - 16, x, y + 16, T.PAL.amber, 0.5);
      G.text(`TAP THE CENTRE · ${this.i + 1 + this.round * 9} / ${this.targets.length * this.rounds}`, x, y - 17, { sz: T.TYPE.small, al: 'center', col: T.PAL.amber });
      for (const s of this.samples) G.disc(s.x, s.y, 1.2, T.alpha(T.PAL.ir, 0.8));
    },
  },

  /* ---------- latency probe: flash a square, time until the camera sees it ---------- */
  async latency(n = 8) {
    const video = T.air.on ? T.air.video : this.cam;
    if (!video || !T.cfg.calib.H_desk_cam) return { ok: false, err: 'needs a calibrated live camera (run Gray-code with the webcam first)' };
    const rect = { x: 30, y: 60, w: 70, h: 70 };
    const [u, v] = this.deskToCam(rect.x + rect.w / 2, rect.y + rect.h / 2);
    const c = document.createElement('canvas'), cw = 160, ch = Math.round(160 * video.videoHeight / video.videoWidth); c.width = cw; c.height = ch; const g = c.getContext('2d', { willReadFrequently: true });
    const probe = () => { g.drawImage(video, 0, 0, cw, ch); const d = g.getImageData(T.clamp(Math.round(u * cw) - 2, 0, cw - 5), T.clamp(Math.round(v * ch) - 2, 0, ch - 5), 5, 5).data; let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i + 1]; return s / 25; };
    const out = [];
    for (let k = 0; k < n; k++) {
      this.flashRect = null; await T.sleep(350); const base = probe();
      let t0 = 0; this.flashRect = rect; await new Promise((r) => requestAnimationFrame(() => { t0 = T.now(); r(); }));
      let t1 = 0; while (T.now() - t0 < 600) { await new Promise((r) => requestAnimationFrame(r)); if (probe() > base + 35) { t1 = T.now(); break; } }
      if (t1) out.push(t1 - t0);
    }
    this.flashRect = null;
    if (!out.length) return { ok: false, err: 'camera never saw the flash — check calibration / exposure' };
    out.sort((a, b) => a - b); const med = out[Math.floor(out.length / 2)];
    T.cfg.calib.latencyMs = med; T.setCfgDirty();
    T.log.info('calib', `projector→camera latency median ${med.toFixed(0)} ms (${out.length}/${n} flashes seen)`);
    return { ok: true, med, samples: out };
  },
};
