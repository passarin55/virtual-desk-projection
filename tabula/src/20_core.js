/* ==========================================================================
   TABULA-Ω · core — namespace, bus, log, storage, math, geometry, filters
   ========================================================================== */
'use strict';
const T = (window.T = window.T || {});
T.VERSION = '1.0.0';
T.BOOT = window.TABULA_BOOT || null;          // injected by tabula_host.py when served (never contains the token)
/* The host's per-run token arrives only in the URL fragment (#t=… — fragments never reach a server or a log).
   It is moved into sessionStorage (this tab, survives reloads) and scrubbed from the address bar. */
T.hashParams = (location.hash || '').replace(/^#/, '').split('&').filter(Boolean);
T.runToken = (() => {
  const p = T.hashParams.find((x) => x.startsWith('t='));
  let t = null;
  if (p) {
    try { t = decodeURIComponent(p.slice(2)); } catch (e) { t = null; }   // a mangled link must not stop the page
    T.hashParams = T.hashParams.filter((x) => !x.startsWith('t='));         // scrub it from the address bar, valid or not
    try { history.replaceState(null, '', location.pathname + location.search + (T.hashParams.length ? '#' + T.hashParams.join('&') : '')); } catch (e) { /* ignore */ }
  }
  if (t && /^[A-Za-z0-9_-]{16,128}$/.test(t)) { try { sessionStorage.setItem('tabula.t', t); } catch (e) { /* storage blocked: memory only */ } }
  else { try { t = sessionStorage.getItem('tabula.t'); } catch (e) { t = null; } }
  return t && /^[A-Za-z0-9_-]{16,128}$/.test(t) ? t : null;
})();
T.setRunToken = (t) => {
  t = String(t || '').trim(); if (!/^[A-Za-z0-9_-]{16,128}$/.test(t)) return false;
  const changed = t !== T.runToken; T.runToken = t;
  try { sessionStorage.setItem('tabula.t', t); } catch (e) { /* ignore */ }
  if (changed && T.link && T.link.chan) T.link.rekey();       // windows of one host run share a channel named after its token
  return true;
};
T.isProjector = T.hashParams[0] === 'projector';

T.now = () => performance.now();
T.clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
T.lerp = (a, b, t) => a + (b - a) * t;
T.dist = (ax, ay, bx, by) => Math.hypot(ax - bx, ay - by);
T.uid = (() => { let n = 0; return (p = 'id') => p + (++n).toString(36) + Math.random().toString(36).slice(2, 5); })();
T.fmt = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '—');
T.deepClone = (o) => JSON.parse(JSON.stringify(o));
T.deepMerge = (dst, src) => {
  if (!src || typeof src !== 'object') return dst;
  for (const k of Object.keys(src)) {
    const v = src[k];
    if (v && typeof v === 'object' && !Array.isArray(v) && dst[k] && typeof dst[k] === 'object' && !Array.isArray(dst[k])) T.deepMerge(dst[k], v);
    else dst[k] = v;
  }
  return dst;
};
T.escapeHTML = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
T.sleep = (ms) => new Promise((r) => setTimeout(r, ms));
T.os = (() => {
  const p = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '').toLowerCase();
  if (p.includes('mac')) return 'mac';
  if (p.includes('win')) return 'win';
  return 'linux';
})();

/* ---------------- event bus ---------------- */
T.bus = {
  h: new Map(),
  on(ev, fn) { if (!this.h.has(ev)) this.h.set(ev, new Set()); this.h.get(ev).add(fn); return () => this.h.get(ev).delete(fn); },
  emit(ev, data) { const s = this.h.get(ev); if (!s) return; for (const fn of [...s]) { try { fn(data); } catch (e) { console.error('[bus]', ev, e); } } },
};

/* ---------------- safe storage (artifact frames may block it) ---------------- */
T.store = {
  get(k, dflt) { try { const s = localStorage.getItem('tabula.' + k); return s ? JSON.parse(s) : dflt; } catch (e) { return dflt; } },
  set(k, v) { try { localStorage.setItem('tabula.' + k, JSON.stringify(v)); return true; } catch (e) { return false; } },
};

/* ---------------- ring-buffer log → inspector ---------------- */
T.log = {
  buf: [], max: 500, seq: 0,
  push(level, src, msg, data) {
    const e = { n: ++this.seq, t: Date.now(), level, src, msg, data };
    this.buf.push(e); if (this.buf.length > this.max) this.buf.shift();
    T.bus.emit('log', e);
    return e;
  },
  info(src, msg, data) { return this.push('info', src, msg, data); },
  act(src, msg, data) { return this.push('act', src, msg, data); },
  warn(src, msg, data) { return this.push('warn', src, msg, data); },
  err(src, msg, data) { console.error('[' + src + ']', msg, data || ''); return this.push('err', src, msg, data); },
};

/* ---------------- linear algebra ---------------- */
T.la = {
  /* solve A x = b (A: n×n array of rows, b: n) — Gaussian elimination, partial pivot. returns null if singular */
  solve(A, b) {
    const n = b.length, M = A.map((r, i) => [...r, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c, best = Math.abs(M[c][c]);
      for (let r = c + 1; r < n; r++) { const v = Math.abs(M[r][c]); if (v > best) { best = v; p = r; } }
      if (best < 1e-12) return null;
      if (p !== c) { const t = M[p]; M[p] = M[c]; M[c] = t; }
      const piv = M[c][c];
      for (let r = c + 1; r < n; r++) {
        const f = M[r][c] / piv; if (f === 0) continue;
        for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
      }
    }
    const x = new Array(n).fill(0);
    for (let r = n - 1; r >= 0; r--) {
      let s = M[r][n];
      for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k];
      x[r] = s / M[r][r];
    }
    return x.every(Number.isFinite) ? x : null;
  },
};

/* ---------------- 3×3 matrices (row-major, length 9) ---------------- */
T.m3 = {
  I: () => [1, 0, 0, 0, 1, 0, 0, 0, 1],
  mul(a, b) {
    const r = new Array(9);
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
    return r;
  },
  det(m) { return m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6]); },
  inv(m) {
    const d = T.m3.det(m); if (!d || !Number.isFinite(d)) return null;
    const r = [
      m[4] * m[8] - m[5] * m[7], m[2] * m[7] - m[1] * m[8], m[1] * m[5] - m[2] * m[4],
      m[5] * m[6] - m[3] * m[8], m[0] * m[8] - m[2] * m[6], m[2] * m[3] - m[0] * m[5],
      m[3] * m[7] - m[4] * m[6], m[1] * m[6] - m[0] * m[7], m[0] * m[4] - m[1] * m[3],
    ];
    return r.map((v) => v / d);
  },
  norm(m) { const s = m[8] || 1; return m.map((v) => v / s); },
  apply(m, x, y) { const w = m[6] * x + m[7] * y + m[8]; return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w]; },
  scale: (sx, sy) => [sx, 0, 0, 0, sy, 0, 0, 0, 1],
  translate: (tx, ty) => [1, 0, tx, 0, 1, ty, 0, 0, 1],
  /* condition number estimate via Frobenius norms of m and inv(m) */
  cond(m) { const i = T.m3.inv(m); if (!i) return Infinity; const f = (a) => Math.sqrt(a.reduce((s, v) => s + v * v, 0)); return f(m) * f(i); },
};

/* ---------------- homographies ---------------- */
T.geom = {
  /* Hartley normalisation: centroid → origin, mean distance → √2 */
  normT(pts) {
    let cx = 0, cy = 0; for (const p of pts) { cx += p[0]; cy += p[1]; }
    cx /= pts.length; cy /= pts.length;
    let md = 0; for (const p of pts) md += Math.hypot(p[0] - cx, p[1] - cy);
    md /= pts.length; const s = md > 1e-12 ? Math.SQRT2 / md : 1;
    return [s, 0, -s * cx, 0, s, -s * cy, 0, 0, 1];
  },
  /* least-squares homography (h33 = 1) on normalised coordinates; src,dst: [[x,y],...], N ≥ 4 */
  dlt(src, dst) {
    const n = src.length; if (n < 4) return null;
    const Ts = T.geom.normT(src), Td = T.geom.normT(dst);
    const s = src.map((p) => T.m3.apply(Ts, p[0], p[1])), d = dst.map((p) => T.m3.apply(Td, p[0], p[1]));
    // normal equations AtA (8×8) h = Atb
    const AtA = Array.from({ length: 8 }, () => new Array(8).fill(0)), Atb = new Array(8).fill(0);
    const acc = (row, rhs) => { for (let i = 0; i < 8; i++) { if (!row[i]) continue; Atb[i] += row[i] * rhs; for (let j = 0; j < 8; j++) AtA[i][j] += row[i] * row[j]; } };
    for (let i = 0; i < n; i++) {
      const [x, y] = s[i], [u, v] = d[i];
      acc([x, y, 1, 0, 0, 0, -u * x, -u * y], u);
      acc([0, 0, 0, x, y, 1, -v * x, -v * y], v);
    }
    const h = T.la.solve(AtA, Atb); if (!h) return null;
    const Hn = [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
    const TdI = T.m3.inv(Td); if (!TdI) return null;
    return T.m3.norm(T.m3.mul(TdI, T.m3.mul(Hn, Ts)));
  },
  /* exact 4-point homography (unit-safe) */
  quadToQuad(srcQ, dstQ) { return T.geom.dlt(srcQ, dstQ); },
  err(H, s, d) { const [x, y] = T.m3.apply(H, s[0], s[1]); return Math.hypot(x - d[0], y - d[1]); },
  rms(H, src, dst, idx) {
    let e = 0, n = 0; const L = idx || src.map((_, i) => i);
    for (const i of L) { const r = T.geom.err(H, src[i], dst[i]); if (Number.isFinite(r)) { e += r * r; n++; } }
    return n ? Math.sqrt(e / n) : NaN;
  },
  triArea(a, b, c) { return Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2; },
  degenerate(p) { // any 3 of 4 nearly collinear?
    const [a, b, c, d] = p; const min = 1e-6 * (1 + Math.abs(a[0]) + Math.abs(a[1])) ** 2;
    return T.geom.triArea(a, b, c) < min || T.geom.triArea(a, b, d) < min || T.geom.triArea(a, c, d) < min || T.geom.triArea(b, c, d) < min;
  },
  /* RANSAC homography with adaptive iteration count k = log(1-p)/log(1-w^4) */
  ransac(src, dst, opt = {}) {
    const n = src.length, thr = opt.thresh ?? 3, maxIt = opt.iters ?? 2000, p = opt.confidence ?? 0.995, rnd = opt.rng || Math.random;
    if (n < 4) return null;
    let best = null, bestIn = [], k = maxIt;
    for (let it = 0; it < k && it < maxIt; it++) {
      const ids = new Set(); while (ids.size < 4) ids.add((rnd() * n) | 0);
      const I = [...ids], s4 = I.map((i) => src[i]), d4 = I.map((i) => dst[i]);
      if (T.geom.degenerate(s4) || T.geom.degenerate(d4)) continue;
      const H = T.geom.dlt(s4, d4); if (!H) continue;
      const inl = []; for (let i = 0; i < n; i++) if (T.geom.err(H, src[i], dst[i]) < thr) inl.push(i);
      if (inl.length > bestIn.length) {
        best = H; bestIn = inl;
        const w = inl.length / n; const denom = Math.log(1 - Math.pow(w, 4));
        k = denom < 0 ? Math.min(maxIt, Math.ceil(Math.log(1 - p) / denom)) : maxIt;
      }
    }
    if (!best || bestIn.length < 4) return null;
    // refine on inliers (2 rounds)
    let H = T.geom.dlt(bestIn.map((i) => src[i]), bestIn.map((i) => dst[i])) || best;
    let inl = []; for (let i = 0; i < n; i++) if (T.geom.err(H, src[i], dst[i]) < thr) inl.push(i);
    if (inl.length >= 4) { const H2 = T.geom.dlt(inl.map((i) => src[i]), inl.map((i) => dst[i])); if (H2) H = H2; }
    inl = []; for (let i = 0; i < n; i++) if (T.geom.err(H, src[i], dst[i]) < thr) inl.push(i);
    return { H, inliers: inl, rms: T.geom.rms(H, src, dst, inl), ratio: inl.length / n };
  },
  polyArea(q) { let a = 0; for (let i = 0; i < q.length; i++) { const p = q[i], r = q[(i + 1) % q.length]; a += p[0] * r[1] - r[0] * p[1]; } return a / 2; },
  isConvexQuad(q) {
    let sign = 0;
    for (let i = 0; i < 4; i++) {
      const a = q[i], b = q[(i + 1) % 4], c = q[(i + 2) % 4];
      const z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
      if (Math.abs(z) < 1e-9) return false;
      const s = Math.sign(z); if (!sign) sign = s; else if (s !== sign) return false;
    }
    return true;
  },
  pointInPoly(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  },
  rectOverlap(a, b) {
    const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return w > 0 && h > 0 ? w * h : 0;
  },
  convexHull(pts) { // monotone chain
    const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]); if (p.length < 3) return p;
    const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    up.pop(); lo.pop(); return lo.concat(up);
  },
};

/* ---------------- One Euro filter (Casiez, Roussel, Vogel — CHI 2012) ---------------- */
T.OneEuro = class {
  constructor(minCutoff = 1.0, beta = 0.007, dCutoff = 1.0) { this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff; this.x = null; this.dx = 0; this.t = null; }
  static alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  reset() { this.x = null; this.dx = 0; this.t = null; }
  filter(x, tSec) {
    if (this.t === null) { this.x = x; this.dx = 0; this.t = tSec; return x; }
    const dt = Math.max(1e-4, tSec - this.t);
    const dx = (x - this.x) / dt;
    const edx = this.dx + T.OneEuro.alpha(this.dCutoff, dt) * (dx - this.dx);
    const cut = this.minCutoff + this.beta * Math.abs(edx);
    const ex = this.x + T.OneEuro.alpha(cut, dt) * (x - this.x);
    this.x = ex; this.dx = edx; this.t = tSec; return ex;
  }
};
T.OneEuro2 = class {
  constructor(p) { this.fx = new T.OneEuro(p.minCutoff, p.beta, p.dCutoff); this.fy = new T.OneEuro(p.minCutoff, p.beta, p.dCutoff); }
  filter(x, y, tSec) { return [this.fx.filter(x, tSec), this.fy.filter(y, tSec)]; }
  velocity() { return [this.fx.dx, this.fy.dx]; }
};

/* ---------------- Gray-code structured light ---------------- */
T.gray = {
  bits: (n) => Math.max(1, Math.ceil(Math.log2(Math.max(2, n)))),
  enc: (i) => i ^ (i >> 1),
  dec(g) { let b = g; for (let s = g >> 1; s; s >>= 1) b ^= s; return b; },
  /* pattern plan for a W×H surface with stripes of `step` px. MSB first (coarse → fine). */
  plan(W, H, step) {
    const nx = Math.ceil(W / step), ny = Math.ceil(H / step), bx = T.gray.bits(nx), by = T.gray.bits(ny);
    const pats = [{ kind: 'black' }, { kind: 'white' }];
    for (let b = 0; b < bx; b++) { pats.push({ kind: 'bit', axis: 'x', b, inv: false }); pats.push({ kind: 'bit', axis: 'x', b, inv: true }); }
    for (let b = 0; b < by; b++) { pats.push({ kind: 'bit', axis: 'y', b, inv: false }); pats.push({ kind: 'bit', axis: 'y', b, inv: true }); }
    return { W, H, step, nx, ny, bx, by, pats };
  },
  /* draw pattern `pat` of `plan` into a 2D ctx whose units are surface pixels */
  draw(ctx, plan, pat) {
    const { W, H, step } = plan;
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = pat.kind === 'white' ? '#fff' : '#000'; ctx.fillRect(0, 0, W, H);
    if (pat.kind === 'bit') {
      ctx.fillStyle = '#fff';
      const nb = pat.axis === 'x' ? plan.bx : plan.by, n = pat.axis === 'x' ? plan.nx : plan.ny, shift = nb - 1 - pat.b;
      let runStart = -1;
      for (let i = 0; i <= n; i++) {
        const on = i < n && ((((T.gray.enc(i) >> shift) & 1) ^ (pat.inv ? 1 : 0)) === 1);
        if (on && runStart < 0) runStart = i;
        if (!on && runStart >= 0) {
          if (pat.axis === 'x') ctx.fillRect(runStart * step, 0, (i - runStart) * step, H);
          else ctx.fillRect(0, runStart * step, W, (i - runStart) * step);
          runStart = -1;
        }
      }
    }
    ctx.restore();
  },
  /* frames: Map-like array aligned with plan.pats, each a Float32Array/Uint8Array luminance image (w×h).
     returns { col, row, valid, conf } Int32/Uint8 arrays of size w×h */
  decode(plan, frames, w, h, opt = {}) {
    const thrB = opt.thrBlack ?? 24, thrW = opt.thrWhite ?? 4;
    const B = frames[0], Wt = frames[1], N = w * h;
    const col = new Int32Array(N).fill(-1), row = new Int32Array(N).fill(-1), valid = new Uint8Array(N);
    let ok = 0;
    for (let i = 0; i < N; i++) {
      if (Wt[i] - B[i] <= thrB) continue;
      let gx = 0, gy = 0, bad = false;
      for (let b = 0; b < plan.bx && !bad; b++) {
        const v = frames[2 + 2 * b][i], vi = frames[3 + 2 * b][i];
        if (Math.abs(v - vi) < thrW) bad = true; gx = (gx << 1) | (v > vi ? 1 : 0);
      }
      const off = 2 + 2 * plan.bx;
      for (let b = 0; b < plan.by && !bad; b++) {
        const v = frames[off + 2 * b][i], vi = frames[off + 1 + 2 * b][i];
        if (Math.abs(v - vi) < thrW) bad = true; gy = (gy << 1) | (v > vi ? 1 : 0);
      }
      if (bad) continue;
      const cx = T.gray.dec(gx), cy = T.gray.dec(gy);
      if (cx >= plan.nx || cy >= plan.ny) continue;
      col[i] = cx; row[i] = cy; valid[i] = 1; ok++;
    }
    return { col, row, valid, ok };
  },
  /* one correspondence per decoded cell: centroid of camera pixels ↔ cell centre (surface px) */
  correspondences(plan, dec, w, h, minPx = 2) {
    const cells = new Map();
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x; if (!dec.valid[i]) continue;
      const key = dec.row[i] * plan.nx + dec.col[i];
      let c = cells.get(key); if (!c) { c = { sx: 0, sy: 0, n: 0, col: dec.col[i], row: dec.row[i] }; cells.set(key, c); }
      c.sx += x + 0.5; c.sy += y + 0.5; c.n++;
    }
    const cam = [], surf = [];
    for (const c of cells.values()) {
      if (c.n < minPx) continue;
      cam.push([c.sx / c.n, c.sy / c.n]);
      surf.push([(c.col + 0.5) * plan.step, (c.row + 0.5) * plan.step]);
    }
    return { cam, surf, cells: cells.size };
  },
};

/* ---------------- small seeded RNG (tests & sims) ---------------- */
T.rng = (seed = 1) => { let s = seed >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; };

/* ---------------- chord helpers ---------------- */
/* the OS whose shortcuts matter is the host's (the machine being driven), falling back to this browser's */
T.targetOS = () => (T.host && T.host.info && T.host.info.os) || T.os;
T.chord = {
  /* per-OS pick: chord may be string, array (sequence) or {win,mac,linux,all} */
  pick(c) { if (c == null) return null; if (typeof c === 'string' || Array.isArray(c)) return c; const os = T.targetOS(); return c[os] ?? c.all ?? null; },
  pretty(c) {
    const s = T.chord.pick(c); if (s == null) return '';
    const mac = T.targetOS() === 'mac';
    const one = (x) => (x === '+' ? '+' : x.split('+').map((k) => {
      const m = { mod: mac ? '⌘' : 'Ctrl', cmd: '⌘', ctrl: mac ? '⌃' : 'Ctrl', alt: mac ? '⌥' : 'Alt', shift: '⇧', win: mac ? '⌘' : 'Win', super: 'Super', left: '←', right: '→', up: '↑', down: '↓', enter: '⏎', esc: 'Esc', space: 'Space', tab: 'Tab', backspace: '⌫', delete: 'Del', pageup: 'PgUp', pagedown: 'PgDn', numpad_dec: 'Num.', numpad_add: 'Num+', numpad_sub: 'Num−', print: 'PrtSc' };
      return m[k] || (k.length === 1 ? k.toUpperCase() : k.replace(/^f(\d+)$/i, 'F$1').replace(/^numpad_?/, 'Num'));
    }).join(mac ? '' : '+'));
    return Array.isArray(s) ? s.map(one).join(' , ') : one(s);
  },
};
