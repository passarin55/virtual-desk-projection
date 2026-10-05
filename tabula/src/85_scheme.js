/* ==========================================================================
   TABULA-Ω · projection scheme — optics, brightness, legibility, sensing and
   latency budget computed from the chosen hardware, plus live side-elevation
   and plan drawings. Formulas and constants are cited in the DOSSIER.
   ========================================================================== */
'use strict';

T.scheme = {
  proj(sc) { return sc.projector === 'custom' && sc.custom ? Object.assign({}, T.PROJECTORS.custom, sc.custom) : (T.PROJECTORS[sc.projector] || T.PROJECTORS['epson-ef21']); },
  compute(cfg = T.cfg) {
    const sc = cfg.scheme, P = this.proj(sc), S = T.SENSORS[sc.sensor] || T.SENSORS['femto-bolt-nfov'];
    const deg = Math.PI / 180, W = cfg.desk.w, H = W * P.res[1] / P.res[0];
    const Tr = P.tr[0], D = Tr * W;                                   // throw distance = ratio × width
    const fold = sc.mount === 'fold', tilt = sc.mount === 'tilt';
    const d1 = fold ? Math.min(Math.max(80, sc.d1), D * 0.7) : 0, d2 = D - d1;
    // fold mirror (45°): width = beam width at d1; length along fold from the ray-angle span (t = tan θ in the fold plane)
    const tr = P.offset >= 100 ? [0, H / D] : [-(H / 2) / D, (H / 2) / D];
    const fA = (t) => t / (1 + t), fB = (t) => t / (1 - t);
    const mirror = fold ? { w: d1 / Tr, La: Math.SQRT2 * d1 * (fA(tr[1]) - fA(tr[0])), Lb: tr[1] < 1 ? Math.SQRT2 * d1 * (fB(tr[1]) - fB(tr[0])) : Infinity } : null;
    if (mirror) { mirror.L = Math.min(mirror.La, mirror.Lb); mirror.good = mirror.La <= mirror.Lb ? 'A' : 'B'; mirror.wM = mirror.w * 1.15; mirror.LM = mirror.L * 1.15; }
    // tilted mount (no lens offset compensation): keystone needed + usable fraction
    let key = null;
    if (tilt) { const beta = Math.atan((H / 2) / D), alpha = Math.atan((H / 2) / D) + 5 * deg; key = { alpha: alpha / deg, usable: Math.cos(alpha + beta) / Math.cos(alpha - beta) }; }
    // brightness & contrast (ISCR ≈ 1 + E_proj / E_ambient; desk reflectance cancels for a Lambertian surface)
    const A = W * H / 1e6, E = P.lm * sc.derate / A, iscr = 1 + E / sc.ambient;
    const need = (c) => (c - 1) * sc.ambient * A / sc.derate;
    const cls = iscr >= 80 ? 'full-motion video' : iscr >= 50 ? 'analytical decisions' : iscr >= 15 ? 'basic decisions' : iscr >= 7 ? 'passive viewing' : 'below passive viewing';
    const Lw = sc.refl * (E + sc.ambient) / Math.PI, Lb = sc.refl * sc.ambient / Math.PI;
    // resolution & legibility (ISO 9241-303 / HFES 100: 16′ minimum, 20–22′ preferred), foreshortened by 1/sin(elevation)
    const pitch = W / P.res[0], elev = 1 / Math.sin(sc.viewElev * deg);
    const cap = (am) => 2 * sc.viewDist * Math.tan((am / 60) * deg / 2) * elev;
    const leg = [16, 22, 24].map((am) => ({ am, mm: cap(am), px: cap(am) / pitch, em: cap(am) / T.TYPE.capRatio }));
    // sensing
    const h = sc.sensorH, fp = [2 * h * Math.tan(S.fov[0] * deg / 2), 2 * h * Math.tan(S.fov[1] * deg / 2)];
    const covers = (fp[0] >= W && fp[1] >= H) || (fp[1] >= W && fp[0] >= H);
    const depthPx = Math.min(fp[0] / S.res[0], fp[1] / S.res[1]);
    const inRange = h / 1000 >= S.range[0] && h / 1000 <= S.range[1];
    const depthCam = /ToF|stereo/i.test(S.kind);
    const band = depthCam ? { lo: Math.max(2, 3 + (h - 750) * 3 / 750), hi: 14 + (h - 750) * 16 / 750 } : null;   // Wilson ITS 2010: 3–14 mm @0.75 m, 6–30 mm @1.5 m
    const acc = depthCam ? 7 * h / 750 : S.kind === 'IR curtain' ? 4 : 12;       // worst-case depth-only error scales with range
    const accFused = depthCam ? Math.min(acc, 4.8 * h / 1600 * 1.0 + 1.5) : acc;  // DIRECT: 4.8 mm at 1.6 m with IR+depth fusion
    const minTarget = Math.max(15, 2.3 * acc);
    // latency budget (ms)
    const cf = 1000 / S.fps;
    const lat = [['sensor exposure (½ frame)', cf / 2], ['sensor readout + USB', cf], ['touch engine', sc.procMs], ['WebSocket', 1], ['render + vsync wait', 1.5 * 1000 / sc.projHz], ['projector input lag', P.lag]];
    const total = lat.reduce((s, x) => s + x[1], 0);
    // camera exposure advice (DLP sequential colour + mains flicker at 2×f_mains)
    const pf = 1000 / sc.projHz, lf = 1000 / (2 * sc.mains), seq = /sequential/.test(P.color);
    const lcm = (a, b) => { for (let k = 1; k < 60; k++) { const v = a * k; if (Math.abs(v / b - Math.round(v / b)) < 0.01) return v; } return a * b; };
    const expo = { projFrame: pf, lightFlicker: lf, common: seq ? lcm(pf, lf) : lf, seq };
    // safety & mounting
    // side view (x = desk depth from the near edge, y = height): where is the (virtual) lens, and is a seated eye inside the beam?
    const lensX = fold ? (P.offset >= 100 ? H : H / 2) : (P.offset >= 100 ? H : H / 2), lensH = fold ? d2 : D;
    const eye = [-240, 450], lensPos = [lensX, lensH];
    const inTri = (p, a, b, c) => { const s = (u, v, w) => (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1]); const d1_ = s(p, a, b), d2_ = s(p, b, c), d3 = s(p, c, a); return !((d1_ < 0 || d2_ < 0 || d3 < 0) && (d1_ > 0 || d2_ > 0 || d3 > 0)); };
    const eyeInBeam = inTri(eye, lensPos, [0, 0], [H, 0]);
    const eyeToLens = Math.hypot(lensPos[0] - eye[0], lensPos[1] - eye[1]);
    const lamp = /lamp/i.test(P.tech);
    return { P, S, W, H, Tr, D, d1, d2, fold, tilt, mirror, key, A, E, iscr, cls, need, Lw, Lb, pitch, elev, leg, fp, covers, depthPx, inRange, band, acc, accFused, minTarget, lat, total, expo, lensH, lensPos, eyeInBeam, eyeToLens, lamp, sensorH: h };
  },
  bom(r) {
    const out = [
      ['Projector', `${r.P.name} — ${r.P.tech}, ${r.P.lm} lm, throw ${r.P.tr.join('–')}, ${r.P.res.join('×')}`, `${r.P.orient}; ${r.P.color}`],
      ['Mount', r.fold ? `Horizontal projector at ${Math.round(r.d2)} mm above desk + 45° first-surface mirror` : r.tilt ? 'Angled arm (digital keystone — loses pixels)' : `Boom/ceiling plate, lens ${Math.round(r.D)} mm above desk, axis ⟂ desk`, 'Disable the projector keystone; TABULA warps on the GPU'],
    ];
    if (r.mirror) out.push(['Fold mirror', `First-surface (front-silvered), ≥ ${Math.ceil(r.mirror.wM)} × ${Math.ceil(r.mirror.LM)} mm`, `orientation ${r.mirror.good}; second-surface glass ghosts (≈4% front reflection)`]);
    out.push(['Depth sensor', `${r.S.name} at ${r.sensorH} mm`, `${r.S.sdk}; ${r.S.kind}, ${r.S.fps} fps`]);
    out.push(['Touch option', '850 nm Class-1 line laser (Powell lens) 1–2 mm above the desk + IR-pass camera', 'sharpest touch-down detection (light-curtain method)']);
    out.push(['Capture camera', '4K webcam near the projector lens', 'document OCR needs far more pixels than tracking (Wellner 1993)']);
    out.push(['Desk surface', 'Matte white / light-grey mat, gain ≈ 1.0', 'gloss reflects a hotspot when you lean over']);
    out.push(['Tokens', 'ArUco MIP 36h12 markers, 30–40 mm, printed', 'python tabula_host.py --print-tokens tokens.svg']);
    out.push(['Host', 'Your PC + Chrome/Edge (Window Management API for the projector screen)', 'python tabula_host.py → http://127.0.0.1:7777']);
    return out;
  },

  /* ---------- drawings (inline SVG, theme-aware through CSS classes) ---------- */
  sideSVG(r) {
    const pad = 110, deskL = -330, deskR = r.H + 170, top = Math.max(r.D, r.sensorH, 900) + 120;
    const vw = deskR - deskL + pad * 2, vh = top + 170;
    const X = (x) => x - deskL + pad, Y = (y) => top - y + 20;
    const o = [];
    o.push(`<svg viewBox="0 0 ${vw} ${vh}" class="scheme-svg" role="img" aria-label="Side elevation of the projection rig">`);
    o.push(`<defs><pattern id="hatch" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="14" class="sv-hatch"/></pattern></defs>`);
    // desk
    o.push(`<rect x="${X(deskL + 40)}" y="${Y(0)}" width="${deskR - deskL - 80}" height="34" class="sv-desk"/><rect x="${X(deskL + 40)}" y="${Y(0) + 34}" width="${deskR - deskL - 80}" height="40" fill="url(#hatch)" class="sv-desk-h"/>`);
    // monitor at the back
    o.push(`<rect x="${X(r.H + 70)}" y="${Y(420)}" width="22" height="330" class="sv-obj"/><rect x="${X(r.H + 60)}" y="${Y(90)}" width="42" height="90" class="sv-obj"/>`);
    // seated user
    const ex = -240, ey = 450;
    o.push(`<circle cx="${X(ex)}" cy="${Y(ey)}" r="62" class="sv-user"/><path d="M${X(ex - 30)} ${Y(ey - 70)} L${X(ex - 60)} ${Y(-40)} M${X(ex + 10)} ${Y(ey - 110)} Q${X(ex + 120)} ${Y(ey - 190)} ${X(r.H * 0.35)} ${Y(8)}" class="sv-user-l"/>`);
    // beam
    let lens, beamPts;
    const x0 = 0, x1 = r.H;
    if (r.fold) {
      const mx = r.P.offset >= 100 ? r.H : r.H / 2, my = r.d2, Lm = r.mirror.L, dx = Lm / Math.SQRT2 / 2;
      lens = [mx + r.d1, my];
      o.push(`<rect x="${X(mx + r.d1)}" y="${Y(my + 70)}" width="260" height="140" rx="10" class="sv-proj"/><text x="${X(mx + r.d1 + 130)}" y="${Y(my - 100)}" class="sv-lbl" text-anchor="middle">projector (horizontal)</text>`);
      o.push(`<polygon points="${X(lens[0])},${Y(lens[1])} ${X(mx + dx)},${Y(my + dx)} ${X(x1)},${Y(0)} ${X(x0)},${Y(0)} ${X(mx - dx)},${Y(my - dx)}" class="sv-beam"/>`);
      o.push(`<line x1="${X(mx - dx)}" y1="${Y(my - dx)}" x2="${X(mx + dx)}" y2="${Y(my + dx)}" class="sv-mirror"/><text x="${X(mx - dx - 20)}" y="${Y(my + dx + 30)}" class="sv-lbl" text-anchor="end">45° first-surface mirror ${Math.ceil(r.mirror.w)}×${Math.ceil(r.mirror.L)} mm</text>`);
      o.push(this.dim(X(mx), Y(my), X(lens[0]), Y(my), `d₁ ${Math.round(r.d1)}`, 'h', -34));
      o.push(this.dim(X(mx), Y(0), X(mx), Y(my), `d₂ ${Math.round(r.d2)}`, 'v', 44));
    } else {
      const lx = r.P.offset >= 100 ? r.H : r.H / 2;
      lens = [lx, r.D];
      o.push(`<rect x="${X(lx - 110)}" y="${Y(r.D + 240)}" width="220" height="240" rx="10" class="sv-proj"/><text x="${X(lx)}" y="${Y(r.D + 270)}" class="sv-lbl" text-anchor="middle">projector (lens down)</text>`);
      o.push(`<polygon points="${X(lx)},${Y(r.D)} ${X(x1)},${Y(0)} ${X(x0)},${Y(0)}" class="sv-beam"/>`);
      o.push(this.dim(X(lx), Y(0), X(lx), Y(r.D), `throw ${Math.round(r.D)} mm`, 'v', r.P.offset >= 100 ? 52 : 70));
    }
    // sensor frustum (depth direction uses the vertical FOV)
    const sx = r.H / 2 - 60, sh = r.sensorH, half = sh * Math.tan(r.S.fov[1] * Math.PI / 360);
    o.push(`<polygon points="${X(sx)},${Y(sh)} ${X(sx + half)},${Y(0)} ${X(sx - half)},${Y(0)}" class="sv-ir"/><rect x="${X(sx - 45)}" y="${Y(sh + 28)}" width="90" height="28" rx="5" class="sv-sensor"/>`);
    o.push(`<text x="${X(sx - 60)}" y="${Y(sh + 10)}" class="sv-lbl sv-lbl-ir" text-anchor="end">${r.S.name.split(' · ')[0]} @ ${sh} mm</text>`);
    // image extent + eye→lens
    o.push(this.dim(X(x0), Y(0) + 96, X(x1), Y(0) + 96, `image depth ${Math.round(r.H)} mm`, 'h', 0));
    o.push(`<line x1="${X(ex)}" y1="${Y(ey)}" x2="${X(lens[0])}" y2="${Y(lens[1])}" class="sv-eye"/><text x="${X((ex + lens[0]) / 2)}" y="${Y((ey + lens[1]) / 2) - 10}" class="sv-lbl sv-lbl-warn" text-anchor="middle">eye → lens ≈ ${Math.round(Math.hypot(lens[0] - ex, lens[1] - ey))} mm · keep ≤ RG2</text>`);
    o.push(`<text x="${X(deskL + 50)}" y="${Y(0) + 150}" class="sv-cap">SIDE ELEVATION · user ← → wall · millimetres</text></svg>`);
    return o.join('');
  },
  dim(x1, y1, x2, y2, label, dir, off) {
    if (dir === 'v') { const x = x1 + off; return `<line x1="${x}" y1="${y1}" x2="${x}" y2="${y2}" class="sv-dim"/><line x1="${x - 8}" y1="${y1}" x2="${x + 8}" y2="${y1}" class="sv-dim"/><line x1="${x - 8}" y1="${y2}" x2="${x + 8}" y2="${y2}" class="sv-dim"/><text x="${x + 12}" y="${(y1 + y2) / 2}" class="sv-lbl">${label}</text>`; }
    const y = y1 + off; return `<line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}" class="sv-dim"/><line x1="${x1}" y1="${y - 8}" x2="${x1}" y2="${y + 8}" class="sv-dim"/><line x1="${x2}" y1="${y - 8}" x2="${x2}" y2="${y + 8}" class="sv-dim"/><text x="${(x1 + x2) / 2}" y="${y - 12}" class="sv-lbl" text-anchor="middle">${label}</text>`;
  },
  topSVG(r, cfg = T.cfg) {
    const W = r.W, H = r.H, m = 140, vw = W + 2 * m, vh = H + 2 * m + 120;
    const X = (x) => x + m, Y = (y) => y + m + 40;
    const o = [`<svg viewBox="0 0 ${vw} ${vh}" class="scheme-svg" role="img" aria-label="Plan view of the desk, projected image, zones and sensor footprint">`];
    o.push(`<rect x="${X(-110)}" y="${Y(-150)}" width="${W + 220}" height="${H + 230}" rx="18" class="sv-desk"/>`);
    o.push(`<rect x="${X(W / 2 - 330)}" y="${Y(-138)}" width="660" height="26" rx="6" class="sv-obj"/><text x="${X(W / 2)}" y="${Y(-150) - 12}" class="sv-lbl" text-anchor="middle">monitors / wall</text>`);
    o.push(`<rect x="${X(0)}" y="${Y(0)}" width="${W}" height="${H}" class="sv-img"/>`);
    const ws = T.WORKSPACES[T.engine && T.engine.ws ? T.engine.ws : 'DEV'];
    for (const slot of Object.keys(T.SLOTS)) {
      const f = T.SLOTS[slot]; let x = f[0] * W; if (cfg.desk.handed === 'left') x = W - x - f[2] * W;
      const y = f[1] * H, w = f[2] * W, h = f[3] * H, kind = ws[slot];
      if (slot === 'B' && cfg.desk.kb.on) continue;
      o.push(`<rect x="${X(x)}" y="${Y(y)}" width="${w}" height="${h}" rx="6" class="sv-zone"/><text x="${X(x + 10)}" y="${Y(y + 32)}" class="sv-lbl">${slot} · ${kind || '—'}</text>`);
    }
    o.push(`<rect x="${X(4)}" y="${Y(3)}" width="${W - 8}" height="${Math.max(30, Math.min(40, 0.064 * H))}" class="sv-zone"/><text x="${X(14)}" y="${Y(28)}" class="sv-lbl">rail · workspaces · focus · arm · clock · media · panic</text>`);
    if (cfg.desk.kb.on) { const k = cfg.desk.kb; o.push(`<rect x="${X(k.x * W)}" y="${Y(k.y * H)}" width="${k.w * W}" height="${k.h * H}" rx="8" class="sv-obj"/><text x="${X((k.x + k.w / 2) * W)}" y="${Y((k.y + k.h / 2) * H) + 10}" class="sv-lbl" text-anchor="middle">physical keyboard (masked)</text>`); }
    const fx = r.fp[0], fy = r.fp[1];
    o.push(`<rect x="${X(W / 2 - fx / 2)}" y="${Y(H / 2 - fy / 2)}" width="${fx}" height="${fy}" class="sv-foot"/><text x="${X(W / 2 + fx / 2) - 8}" y="${Y(H / 2 - fy / 2) + 34}" class="sv-lbl sv-lbl-ir" text-anchor="end">sensor footprint ${Math.round(fx)}×${Math.round(fy)} mm</text>`);
    o.push(this.dim(X(0), Y(H) + 50, X(W), Y(H) + 50, `image ${Math.round(W)} × ${Math.round(H)} mm · ${r.pitch.toFixed(2)} mm/px`, 'h', 0));
    o.push(`<circle cx="${X(W / 2)}" cy="${Y(H) + 170}" r="46" class="sv-user"/><text x="${X(W / 2) + 64}" y="${Y(H) + 182}" class="sv-lbl">you (${cfg.desk.handed}-handed layout)</text>`);
    o.push(`<text x="${X(-100)}" y="${vh - 10}" class="sv-cap">PLAN · zones for workspace ${T.engine && T.engine.ws ? T.engine.ws : 'DEV'} · millimetres</text></svg>`);
    return o.join('');
  },
};
