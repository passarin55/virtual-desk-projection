/* ==========================================================================
   TABULA-Ω · output — the surface canvas (desk mm → projector pixels) and
   the warp: GPU corner-pin homography + optional mesh (lens/non-planar)
   correction, edge feather, tint gain. 2D affine-triangle fallback.
   Doing the warp here (not with the projector's keystone) keeps pixels and
   avoids the projector's extra processing latency (research: 30–100 ms).
   ========================================================================== */
'use strict';

T.render = {
  surface: null, sctx: null, texW: 1920, texH: 1080,
  init() { this.surface = document.createElement('canvas'); this.resize(); },
  resize() {
    const [rw, rh] = T.cfg.output.res, W = T.cfg.desk.w, H = T.cfg.desk.h;
    // surface keeps the desk aspect; long side = projector native width
    this.texW = rw; this.texH = Math.round(rw * H / W);
    if (this.texH > rh * 1.02) { this.texH = rh; this.texW = Math.round(rh * W / H); }
    this.surface.width = this.texW; this.surface.height = this.texH; this.sctx = this.surface.getContext('2d', { alpha: false });
  },
  pxPerMm() { return this.texW / T.cfg.desk.w; },
};

/* unit square → output quad (normalised output coords) */
T.cornerH = () => T.geom.dlt([[0, 0], [1, 0], [1, 1], [0, 1]], T.cfg.output.corners);
/* bilinear interpolation of mesh offsets (normalised output units) */
T.meshOffset = (s, t) => {
  const m = T.cfg.output.mesh; if (!m || !m.on || !m.d) return [0, 0];
  const fx = s * (m.nx - 1), fy = t * (m.ny - 1), i = Math.min(m.nx - 2, Math.floor(fx)), j = Math.min(m.ny - 2, Math.floor(fy)), u = fx - i, v = fy - j;
  const D = (a, b) => m.d[b * m.nx + a] || [0, 0];
  const a = D(i, j), b = D(i + 1, j), c = D(i, j + 1), d = D(i + 1, j + 1);
  return [a[0] * (1 - u) * (1 - v) + b[0] * u * (1 - v) + c[0] * (1 - u) * v + d[0] * u * v, a[1] * (1 - u) * (1 - v) + b[1] * u * (1 - v) + c[1] * (1 - u) * v + d[1] * u * v];
};
T.warpPoint = (H, s, t) => { const p = T.m3.apply(H, s, t), o = T.meshOffset(s, t); return [p[0] + o[0], p[1] + o[1]]; };

T.warp = {
  gl: null, ok: false, canvas: null, NX: 48, NY: 27, geomKey: '',
  init(canvas) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, preserveDrawingBuffer: true });
    if (!gl) { this.ok = false; T.log.warn('warp', 'WebGL2 unavailable — using 2D triangle warp'); this.ctx2d = canvas.getContext('2d'); return false; }
    this.gl = gl;
    const vs = `#version 300 es
in vec2 aPos; in vec2 aUV; out vec2 vUV;
void main(){ vUV = aUV; gl_Position = vec4(aPos, 0.0, 1.0); }`;
    const fs = `#version 300 es
precision highp float;
uniform sampler2D uTex; uniform vec3 uTint; uniform float uGain; uniform float uFeather;
in vec2 vUV; out vec4 o;
void main(){
  vec3 c = texture(uTex, vUV).rgb * uTint * uGain;
  float f = uFeather > 0.0 ? smoothstep(0.0, uFeather, vUV.x) * smoothstep(0.0, uFeather, 1.0 - vUV.x) * smoothstep(0.0, uFeather, vUV.y) * smoothstep(0.0, uFeather, 1.0 - vUV.y) : 1.0;
  o = vec4(clamp(c, 0.0, 1.0) * f, 1.0);
}`;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    try {
      const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
      this.prog = p;
    } catch (e) { T.log.err('warp', 'shader: ' + e.message); this.ok = false; return false; }
    this.loc = { pos: gl.getAttribLocation(this.prog, 'aPos'), uv: gl.getAttribLocation(this.prog, 'aUV'), tex: gl.getUniformLocation(this.prog, 'uTex'), tint: gl.getUniformLocation(this.prog, 'uTint'), gain: gl.getUniformLocation(this.prog, 'uGain'), feather: gl.getUniformLocation(this.prog, 'uFeather') };
    this.vbo = gl.createBuffer(); this.ibo = gl.createBuffer(); this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const idx = []; const NX = this.NX, NY = this.NY;
    for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) { const a = j * (NX + 1) + i, b = a + 1, c = a + NX + 1, d = c + 1; idx.push(a, b, c, b, d, c); }
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW); this.nIdx = idx.length;
    this.ok = true; return true;
  },
  geometry() {
    const o = T.cfg.output, key = JSON.stringify([o.corners, o.mesh, o.flipX, o.flipY]);
    if (key === this.geomKey) return; this.geomKey = key;
    const H = T.cornerH(); if (!H) return;
    const NX = this.NX, NY = this.NY, v = new Float32Array((NX + 1) * (NY + 1) * 4); let k = 0;
    for (let j = 0; j <= NY; j++) for (let i = 0; i <= NX; i++) {
      const s = i / NX, t = j / NY, p = T.warpPoint(H, s, t);
      v[k++] = p[0] * 2 - 1; v[k++] = 1 - p[1] * 2; v[k++] = o.flipX ? 1 - s : s; v[k++] = o.flipY ? 1 - t : t;
    }
    const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo); gl.bufferData(gl.ARRAY_BUFFER, v, gl.DYNAMIC_DRAW);
  },
  draw(surface) {
    const c = this.canvas, dpr = 1, w = Math.round(c.clientWidth * (window.devicePixelRatio || 1) * dpr), h = Math.round(c.clientHeight * (window.devicePixelRatio || 1) * dpr);
    if (w && h && (c.width !== w || c.height !== h)) { c.width = w; c.height = h; }
    if (!this.ok) return T.warp2d(this.ctx2d || c.getContext('2d'), surface, c.width, c.height);
    const gl = this.gl, o = T.cfg.output; this.geometry();
    gl.viewport(0, 0, c.width, c.height); gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.prog);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, surface);
    gl.uniform1i(this.loc.tex, 0); gl.uniform3fv(this.loc.tint, o.tint); gl.uniform1f(this.loc.gain, o.gain); gl.uniform1f(this.loc.feather, o.feather);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.enableVertexAttribArray(this.loc.pos); gl.vertexAttribPointer(this.loc.pos, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(this.loc.uv); gl.vertexAttribPointer(this.loc.uv, 2, gl.FLOAT, false, 16, 8);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo); gl.drawElements(gl.TRIANGLES, this.nIdx, gl.UNSIGNED_SHORT, 0);
  },
};

/* 2D fallback / preview: affine triangle mapping (each grid cell → two triangles) */
T.warp2d = (g, src, W, H, opt = {}) => {
  const NX = opt.nx || 16, NY = opt.ny || 9, Hm = T.cornerH(); if (!Hm) return;
  const o = T.cfg.output, sw = src.width, sh = src.height;
  g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
  const P = (i, j) => { const s = i / NX, t = j / NY, p = T.warpPoint(Hm, s, t); return { x: p[0] * W, y: p[1] * H, u: (o.flipX ? 1 - s : s) * sw, v: (o.flipY ? 1 - t : t) * sh }; };
  const tri = (A0, A1, A2) => {
    const u0 = A0.u, v0 = A0.v, x0 = A0.x, y0 = A0.y, u1 = A1.u, v1 = A1.v, x1 = A1.x, y1 = A1.y, u2 = A2.u, v2 = A2.v, x2 = A2.x, y2 = A2.y;
    const den = u0 * v1 + v0 * u2 + u1 * v2 - v1 * u2 - v0 * u1 - u0 * v2; if (Math.abs(den) < 1e-9) return;
    const m11 = (x0 * v1 + v0 * x2 + x1 * v2 - v1 * x2 - v0 * x1 - x0 * v2) / den, m21 = (u0 * x1 + x0 * u2 + u1 * x2 - x1 * u2 - x0 * u1 - u0 * x2) / den;
    const dx = (u0 * v1 * x2 + v0 * x1 * u2 + x0 * u1 * v2 - x0 * v1 * u2 - v0 * u1 * x2 - u0 * x1 * v2) / den;
    const m12 = (y0 * v1 + v0 * y2 + y1 * v2 - v1 * y2 - v0 * y1 - y0 * v2) / den, m22 = (u0 * y1 + y0 * u2 + u1 * y2 - y1 * u2 - y0 * u1 - u0 * y2) / den;
    const dy = (u0 * v1 * y2 + v0 * y1 * u2 + y0 * u1 * v2 - y0 * v1 * u2 - v0 * u1 * y2 - u0 * y1 * v2) / den;
    const a = A0, b = A1, c = A2;
    g.save(); g.beginPath();
    const cx = (a.x + b.x + c.x) / 3, cy = (a.y + b.y + c.y) / 3, ex = (p) => [p.x + (p.x - cx) * 0.02, p.y + (p.y - cy) * 0.02];   // tiny overlap hides seams
    const A = ex(a), B = ex(b), C = ex(c); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.lineTo(C[0], C[1]); g.closePath(); g.clip();
    g.setTransform(m11, m12, m21, m22, dx, dy); g.drawImage(src, 0, 0); g.restore();
  };
  for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) { const a = P(i, j), b = P(i + 1, j), c = P(i, j + 1), d = P(i + 1, j + 1); tri(a, b, c); tri(b, d, c); }
};

/* output pixel (normalised) → desk mm, through the inverse corner-pin (mesh offsets ignored: sub-mm) */
T.outToDesk = (u, v) => { const H = T.cornerH(), Hi = H && T.m3.inv(H); if (!Hi) return [null, null]; const [s, t] = T.m3.apply(Hi, u, v); const o = T.cfg.output; const ss = o.flipX ? 1 - s : s, tt = o.flipY ? 1 - t : t; return [ss * T.cfg.desk.w, tt * T.cfg.desk.h]; };
