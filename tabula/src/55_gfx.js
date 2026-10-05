/* ==========================================================================
   TABULA-Ω · projected-surface graphics. Units are desk millimetres.
   Black = no light on the desk, so the palette is luminous strokes on void.
   Type sizes are em sizes in mm, chosen from the legibility research:
   16′ of arc at 600 mm seen at 50° elevation → cap height ≥ 3.6 mm → em ≥ 5.2 mm.
   ========================================================================== */
'use strict';

T.PAL = {
  bg: '#000000', ink: '#e8f3f7', dim: 'rgba(196,222,232,0.62)', faint: 'rgba(124,240,255,0.14)', line: 'rgba(124,240,255,0.45)',
  beam: '#7cf0ff', ir: '#ff5c93', lime: '#b8f55a', amber: '#ffc861', red: '#ff4d4d', green: '#45e39a', violet: '#b69cff', orange: '#ff9f43',
};
T.GROUP_HUE = { edit: 'beam', nav: 'violet', file: 'lime', sys: 'amber', win: 'violet', view: 'beam', debug: 'orange', tool: 'lime', xf: 'amber', obj: 'violet', anim: 'orange', render: 'red', mode: 'beam', color: 'lime', layer: 'violet', tp: 'lime', mark: 'amber', live: 'red', audio: 'amber', filter: 'ir', follow: 'violet', cap: 'red', tab: 'beam', dev: 'orange', ctl: 'amber', git: 'lime', sh: 'beam', gpu: 'ir', fmt: 'beam', style: 'violet', ins: 'lime', rev: 'amber', fx: 'lime', data: 'beam', sel: 'violet', show: 'lime', vol: 'amber', zoom: 'beam', teams: 'violet', discord: 'violet', slack: 'lime', route: 'amber', track: 'violet', scene: 'ir', flow: 'lime', app: 'beam', media: 'amber', xfm: 'amber' };
T.hue = (g) => T.PAL[T.GROUP_HUE[g] || 'beam'];
T.FONT = {
  ui: '"Barlow Semi Condensed", "Barlow", "Arial Narrow", "Roboto Condensed", system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace',
  disp: '"Michroma", "Eurostile", "Barlow Semi Condensed", system-ui, sans-serif',
};
T.TYPE = { min: 5.2, small: 5.6, body: 6.6, title: 7.6, big: 11, huge: 18, capRatio: 0.7 };
T.alpha = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`; };

T.gfx = {
  g: null, s: 1, minFont: Infinity,
  begin(ctx, s) { this.g = ctx; this.s = s; ctx.setTransform(s, 0, 0, s, 0, 0); this.minFont = Infinity; },
  font(sz, w = 500, fam = 'ui') { this.g.font = `${w} ${sz}px ${T.FONT[fam]}`; if (sz < this.minFont) this.minFont = sz; },
  text(str, x, y, o = {}) {
    const g = this.g; this.font(o.sz || T.TYPE.body, o.w || 500, o.fam || 'ui');
    g.fillStyle = o.col || T.PAL.ink; g.textAlign = o.al || 'left'; g.textBaseline = o.bl || 'alphabetic';
    let s = String(str);
    if (o.max) s = this.ellip(s, o.max);
    g.fillText(s, x, y); return g.measureText(s).width;
  },
  /* shrink to fit (down to minSz) then ellipsize */
  fit(str, x, y, maxW, o = {}) {
    let sz = o.sz || T.TYPE.body; const minSz = o.minSz || T.TYPE.min;
    this.font(sz, o.w || 500, o.fam || 'ui');
    while (sz > minSz && this.g.measureText(str).width > maxW) { sz -= 0.2; this.font(sz, o.w || 500, o.fam || 'ui'); }
    return this.text(str, x, y, Object.assign({}, o, { sz, max: maxW }));
  },
  ellip(s, maxW) {
    const g = this.g; if (g.measureText(s).width <= maxW) return s;
    let lo = 0, hi = s.length; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (g.measureText(s.slice(0, m) + '…').width <= maxW) lo = m; else hi = m - 1; }
    return s.slice(0, lo) + '…';
  },
  wrap(str, maxW, o = {}) {
    this.font(o.sz || T.TYPE.body, o.w || 400, o.fam || 'ui');
    const out = [];
    for (const para of String(str).split('\n')) {
      let line = '';
      for (const word of para.split(/\s+/)) {
        const t = line ? line + ' ' + word : word;
        if (this.g.measureText(t).width > maxW && line) { out.push(line); line = word; } else line = t;
      }
      out.push(line);
    }
    return out;
  },
  rr(x, y, w, h, r) { const g = this.g; r = Math.min(r, w / 2, h / 2); g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); },
  ring(x, y, r, col, lw = 0.8) { const g = this.g; g.strokeStyle = col; g.lineWidth = lw; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke(); },
  disc(x, y, r, col) { const g = this.g; g.fillStyle = col; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); },
  line(x1, y1, x2, y2, col, lw = 0.8, dash) { const g = this.g; g.strokeStyle = col; g.lineWidth = lw; g.setLineDash(dash || []); g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); g.setLineDash([]); },
  /* widget chrome: registration ticks at the corners + title tab (a drafting-sheet title block) */
  frame(r, title, o = {}) {
    const g = this.g, col = o.col || T.PAL.line, k = 6;
    g.strokeStyle = T.alpha(o.hue || T.PAL.beam, 0.16); g.lineWidth = 0.6; this.rr(r.x, r.y, r.w, r.h, 3); g.stroke();
    g.strokeStyle = col; g.lineWidth = 1.0; g.beginPath();
    g.moveTo(r.x, r.y + k); g.lineTo(r.x, r.y); g.lineTo(r.x + k, r.y);
    g.moveTo(r.x + r.w - k, r.y); g.lineTo(r.x + r.w, r.y); g.lineTo(r.x + r.w, r.y + k);
    g.moveTo(r.x + r.w, r.y + r.h - k); g.lineTo(r.x + r.w, r.y + r.h); g.lineTo(r.x + r.w - k, r.y + r.h);
    g.moveTo(r.x + k, r.y + r.h); g.lineTo(r.x, r.y + r.h); g.lineTo(r.x, r.y + r.h - k); g.stroke();
    if (title) this.text(title, r.x + 3.5, r.y + 7.4, { sz: T.TYPE.min, w: 600, col: T.alpha(o.hue || T.PAL.beam, 0.85), fam: 'ui' });
  },
  button(r, label, o = {}) {
    const g = this.g, hue = o.hue || T.PAL.beam, on = o.on, pr = o.pressed;
    this.rr(r.x, r.y, r.w, r.h, o.rad ?? 2.4);
    g.fillStyle = T.alpha(hue, pr ? 0.42 : on ? 0.24 : 0.09); g.fill();
    g.strokeStyle = T.alpha(hue, o.disabled ? 0.2 : pr ? 1 : on ? 0.95 : 0.55); g.lineWidth = pr || on ? 1.1 : 0.8; g.stroke();
    const lc = o.disabled ? T.PAL.dim : pr ? '#ffffff' : T.PAL.ink;
    const hint = o.hint && r.h >= 17;
    const ly = hint ? r.y + r.h * 0.46 : r.y + r.h / 2 + T.TYPE.body * 0.34;
    this.fit(label, r.x + r.w / 2, ly, r.w - 3, { sz: o.sz || T.TYPE.body, w: 600, al: 'center', col: lc });
    if (hint) this.fit(o.hint, r.x + r.w / 2, r.y + r.h - 3.2, r.w - 3, { sz: T.TYPE.min, w: 500, al: 'center', col: T.alpha(hue, 0.8), fam: 'ui' });
  },
};

/* ---------------- transient effects: ripples + occlusion-aware callouts ---------------- */
T.fx = {
  ripples: [], callouts: [],
  ripple(x, y, col = T.PAL.beam, r = 14) { this.ripples.push({ x, y, col, r, t: T.now() }); },
  /* place a callout away from the hand that caused it (Vogel & Balakrishnan, CHI 2010): up-left of a right hand, up-right of a left hand */
  callout(x, y, text, o = {}) {
    const W = T.cfg.desk.w, H = T.cfg.desk.h, handed = T.cfg.desk.handed;
    const lines = T.gfx.g ? T.gfx.wrap(text, o.maxW || 120, { sz: T.TYPE.small }) : [text];
    const w = Math.min(o.maxW || 120, Math.max(...lines.map((l) => (T.gfx.g ? T.gfx.g.measureText(l).width : l.length * 2.6))) + 8), h = lines.length * 7.2 + 7;
    const cands = handed === 'left' ? [[18, -h - 18], [18, 18], [-w - 18, -h - 18]] : [[-w - 18, -h - 18], [-w - 18, 18], [18, -h - 18]];
    const hands = T.engine ? T.engine.handPolys() : [];
    let best = null, bestCost = Infinity;
    for (const [dx, dy] of cands) {
      const bx = T.clamp(x + dx, 4, W - w - 4), by = T.clamp(y + dy, 40, H - h - 4);
      let cost = Math.hypot(bx - (x + dx), by - (y + dy));
      for (const hp of hands) for (const [px, py] of [[bx, by], [bx + w, by], [bx, by + h], [bx + w, by + h], [bx + w / 2, by + h / 2]]) if (T.geom.pointInPoly(px, py, hp)) cost += 400;
      if (cost < bestCost) { bestCost = cost; best = [bx, by]; }
    }
    this.callouts.push({ x: best[0], y: best[1], w, h, lines, ax: x, ay: y, t: T.now(), ttl: o.ttl || 2600, col: o.col || T.PAL.beam });
    if (this.callouts.length > 6) this.callouts.shift();
  },
  draw(G, now) {
    const g = G.g;
    this.ripples = this.ripples.filter((r) => now - r.t < 480);
    for (const r of this.ripples) { const k = (now - r.t) / 480; G.ring(r.x, r.y, r.r * (0.4 + k), T.alpha(r.col, 1 - k), 1.2); }
    this.callouts = this.callouts.filter((c) => now - c.t < c.ttl);
    for (const c of this.callouts) {
      const a = Math.min(1, (c.ttl - (now - c.t)) / 300);
      g.globalAlpha = a;
      G.line(c.ax, c.ay, T.clamp(c.ax, c.x, c.x + c.w), T.clamp(c.ay, c.y, c.y + c.h), T.alpha(c.col, 0.7), 0.6, [1.5, 1.5]);
      G.rr(c.x, c.y, c.w, c.h, 2); g.fillStyle = 'rgba(0,0,0,0.92)'; g.fill(); g.strokeStyle = c.col; g.lineWidth = 0.8; g.stroke();
      c.lines.forEach((l, i) => G.text(l, c.x + 4, c.y + 9 + i * 7.2, { sz: T.TYPE.small, col: T.PAL.ink }));
      g.globalAlpha = 1;
    }
  },
};

/* ---------------- grid helper for button walls ---------------- */
T.grid = (area, n, o = {}) => {
  const gap = o.gap ?? 2.5, minW = o.minW ?? 36, minH = o.minH ?? 17;
  let cols = Math.max(1, Math.floor((area.w + gap) / (minW + gap))); if (o.maxCols) cols = Math.min(cols, o.maxCols);
  cols = Math.max(1, Math.min(cols, n || 1));
  const rows = Math.max(1, Math.floor((area.h + gap) / (minH + gap)));
  const perPage = cols * rows;
  const cw = (area.w - gap * (cols - 1)) / cols;
  const usedRows = Math.min(rows, Math.ceil(Math.min(n, perPage) / cols));
  const ch = o.stretch ? Math.min((area.h - gap * (usedRows - 1)) / Math.max(1, usedRows), o.maxH || 30) : minH;
  return { cols, rows, perPage, cw, ch, gap, cell: (i) => { const j = i % perPage, c = j % cols, r = (j / cols) | 0; return { x: area.x + c * (cw + gap), y: area.y + r * (ch + gap), w: cw, h: ch }; } };
};
