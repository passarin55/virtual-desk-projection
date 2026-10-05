/* ==========================================================================
   TABULA-Ω · host link — live WebSocket bridge to tabula_host.py, an in-page
   simulated host (so the desk is fully explorable without hardware), Web MIDI,
   and the action executor every widget goes through.
   ========================================================================== */
'use strict';

/* ---------------- shared host facade ---------------- */
T.host = {
  mode: 'sim',              // 'sim' | 'live' | 'off'
  link: null,               // active implementation (SimHost | LiveHost)
  connected: false, armed: false, info: null, focus: null,
  windows: [], screens: [], telemetry: null, clip: [], obs: null, rtt: null, audit: null,
  pending: new Map(), seq: 0,
  start(mode) {
    if (this.link) { try { this.link.close(); } catch (e) { /* ignore */ } }
    this.mode = mode; this.connected = false; this.armed = false; this.info = null;
    if (mode === 'live') this.link = new T.LiveHost();
    else if (mode === 'sim') this.link = new T.SimHost();
    else this.link = null;
    if (this.link) this.link.open();
    T.bus.emit('host:mode', mode);
  },
  send(msg) { return this.link ? this.link.send(msg) : false; },
  request(msg, timeoutMs = 8000) {
    const id = 'r' + (++this.seq); msg.id = id;
    return new Promise((res) => {
      const to = setTimeout(() => { this.pending.delete(id); res({ ok: false, err: 'timeout' }); }, timeoutMs);
      this.pending.set(id, (m) => { clearTimeout(to); res(m); });
      if (!this.send(msg)) { clearTimeout(to); this.pending.delete(id); res({ ok: false, err: 'host not connected' }); }
    });
  },
  /* called by implementations for every inbound JSON message */
  _in(m) {
    if (m.id && this.pending.has(m.id)) { const f = this.pending.get(m.id); this.pending.delete(m.id); f(m); }
    switch (m.t) {
      case 'welcome':
        this.connected = true; this.info = m.host || {}; this.armed = !!m.armed; this.audit = m.audit || null;
        this.screens = (m.host && m.host.screens) || []; T.log.info('host', `${this.mode === 'sim' ? 'simulated' : 'live'} host ready · ${this.info.os || '?'} · input ${this.info.input || '?'}${this.info.dry ? ' (dry-run)' : ''}`);
        break;
      case 'armed': this.armed = !!m.on; T.log[m.on ? 'warn' : 'info']('host', m.on ? 'ARMED — OS input injection live' : 'disarmed' + (m.reason ? ' · ' + m.reason : '')); break;
      case 'focus': this.focus = m; break;
      case 'windows': this.windows = m.list || []; break;
      case 'screens': this.screens = m.list || []; break;
      case 'telemetry': this.telemetry = m; break;
      case 'clip': this.clip = m.history || []; break;
      case 'obs': this.obs = m; break;
      case 'pong': this.rtt = T.now() - m.ts; break;
      case 'log': T.log.push(m.level || 'info', 'host', m.msg); break;
      case 'ack': if (!m.ok) T.log.warn('host', 'action refused: ' + (m.err || '?')); break;
      case 'portal': if (m.op === 'refused') T.bus.emit('toast', { text: m.err || 'PORTAL refused', kind: 'warn' }); break;
      default: break;
    }
    if (T.engine) T.engine.dirty = true;
    T.bus.emit('host:' + m.t, m);
  },
  _closed(why) {
    const was = this.connected; this.connected = false; this.armed = false;
    for (const f of this.pending.values()) f({ ok: false, err: 'disconnected' }); this.pending.clear();
    if (was) T.log.warn('host', 'link closed' + (why ? ' · ' + why : ''));
    T.bus.emit('host:closed', why);
  },
  ping() { this.send({ t: 'ping', ts: T.now() }); },
  arm(on, gate) { return this.request({ t: 'arm', on: !!on, gate: gate || null }); },
  panic(reason = 'panic') { this.send({ t: 'panic', reason }); this.armed = false; T.log.warn('desk', 'PANIC — released all inputs and disarmed'); T.bus.emit('panic'); },
  /* a follower window has no host link: open a throw-away socket so its PANIC never waits on a busy or hung leader */
  panicDirect(reason = 'panic') {
    if (!T.runToken || (!T.BOOT && !T.cfg.host.url)) return false;
    try {
      const ws = new WebSocket(new T.LiveHost().url());
      ws.onopen = () => { ws.send(JSON.stringify({ t: 'panic', reason: 'follower window: ' + reason })); setTimeout(() => ws.close(), 250); };
      setTimeout(() => { try { ws.close(); } catch (e) { /* ignore */ } }, 4000);
      return true;
    } catch (e) { return false; }
  },
  act(a) {
    if (!this.connected) { T.bus.emit('toast', { text: 'Host offline — action not sent', kind: 'warn' }); return Promise.resolve({ ok: false, err: 'offline' }); }
    if (!this.armed) { T.bus.emit('toast', { text: 'SAFE mode — arm in the TRIBUNAL (or hold the SAFE pill 2 s)', kind: 'warn' }); return Promise.resolve({ ok: false, err: 'not armed' }); }
    T.log.act('act', T.actions.describe(a));
    return this.request({ t: 'act', a });
  },
  ptr(m) { if (this.connected && this.armed) this.send(Object.assign({ t: 'ptr' }, m)); },
};

/* ---------------- live host over WebSocket ---------------- */
T.LiveHost = class {
  constructor() { this.ws = null; this.backoff = 500; this.closed = false; this.pingT = null; }
  token() { return T.runToken || ''; }
  url() {
    if (T.BOOT) return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws?token=' + encodeURIComponent(this.token());
    const u = (T.cfg.host.url || 'ws://127.0.0.1:7777/ws').trim();
    return u + (u.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(this.token());
  }
  /* a handshake refused before it opened: tell a missing/stale token apart from a host that is down */
  async diagnose() {
    if (this.hinted || !T.BOOT) return;
    try {
      const r = await fetch('/health', { cache: 'no-store' });
      if (!r.ok) return;
      this.hinted = true;
      const msg = this.token() ? 'The host refused this page\'s token — it changes every run. Open the link the host printed (…/#t=…), or paste the token in LINK.' : 'This page has no host token. Open the link the host printed (…/#t=…), or paste the token in LINK → Token.';
      T.log.warn('host', msg); T.bus.emit('toast', { text: msg, kind: 'warn' });
    } catch (e) { /* host down: keep retrying quietly */ }
  }
  open() {
    if (this.closed) return;
    if (!this.token()) {                                    // no token: knocking would only fill the host's audit log with rejects
      const msg = 'No host token in this tab. Open the link the host printed (…/#t=…), or paste the token in LINK → Token and press LIVE.';
      T.log.warn('host', msg); T.bus.emit('toast', { text: msg, kind: 'warn' }); T.host.needToken = true; return;
    }
    T.host.needToken = false;
    let ws; try { ws = new WebSocket(this.url()); } catch (e) { T.log.err('host', 'cannot open WebSocket: ' + e.message); return this.retry(); }
    this.ws = ws; ws.binaryType = 'arraybuffer'; let opened = false;
    ws.onopen = () => { opened = true; this.hinted = false; this.backoff = 500; ws.send(JSON.stringify({ t: 'hello', v: 1, role: T.isProjector ? 'projector' : 'console', ua: navigator.userAgent, desk: { w: T.cfg.desk.w, h: T.cfg.desk.h } })); this.pingT = setInterval(() => T.host.ping(), 2000); };
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } T.host._in(m); }
      else T.host._frame(ev.data);
    };
    ws.onclose = (ev) => { clearInterval(this.pingT); T.host._closed(ev.reason || ('code ' + ev.code)); if (!opened) this.diagnose(); if (!this.closed) this.retry(); };
    ws.onerror = () => { /* onclose follows */ };
  }
  retry() { if (this.closed) return; setTimeout(() => this.open(), this.backoff); this.backoff = Math.min(8000, this.backoff * 1.7); }
  send(m) { if (this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(m)); return true; } return false; }
  close() { this.closed = true; clearInterval(this.pingT); if (this.ws) this.ws.close(); }
};
/* binary portal frame: [u32 LE headerLen][header JSON][JPEG bytes] */
T.host._frame = function (buf) {
  try {
    const dv = new DataView(buf), hl = dv.getUint32(0, true);
    const hdr = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
    const blob = new Blob([new Uint8Array(buf, 4 + hl)], { type: hdr.mime || 'image/jpeg' });
    createImageBitmap(blob).then((bmp) => { T.engine.dirty = true; T.bus.emit('host:frame', { hdr, bmp }); }).catch(() => {});
  } catch (e) { T.log.warn('host', 'bad frame: ' + e.message); }
};

/* ---------------- simulated host (dry; nothing leaves the page) ---------------- */
T.SIM_APPS = [
  { app: 'Code', exe: 'code', title: 'tabula_host.py — tabula — Visual Studio Code' },
  { app: 'Chrome', exe: 'chrome', title: 'O-RAN WG3 E2AP spec — Google Chrome' },
  { app: 'Blender', exe: 'blender', title: 'desk_rig.blend — Blender' },
  { app: 'Wireshark', exe: 'wireshark', title: 'n2_capture.pcapng — Wireshark' },
  { app: 'Terminal', exe: 'windowsterminal.exe', title: 'Terminal — ollama serve' },
  { app: 'OBS', exe: 'obs64.exe', title: 'OBS 31.0 — Profile: Desk' },
  { app: 'Ableton Live', exe: 'live', title: 'dropforge_set — Ableton Live 12 Suite' },
  { app: 'Word', exe: 'winword.exe', title: 'Calibration report.docx - Word' },
];
T.SimHost = class {
  constructor() {
    this.timers = []; this.focusIdx = 0; this.editor = { lines: T.SimHost.seedLines(), scroll: 0, caret: { l: 11, c: 4 }, flash: 0, ripples: [] };
    this.cursor = [700, 420]; this.portal = null; this.canvas = null;
    this.screens = [{ id: 0, name: 'DISPLAY 1', x: 0, y: 0, w: 2560, h: 1440, primary: true, scale: 1.25 }, { id: 1, name: 'DISPLAY 2', x: 2560, y: 180, w: 1920, h: 1080, primary: false, scale: 1 }];
    this.wins = [
      { id: 101, title: 'tabula_host.py — Visual Studio Code', app: 'code', rect: [60, 40, 1500, 1300], min: false },
      { id: 102, title: 'O-RAN WG3 E2AP spec — Google Chrome', app: 'chrome', rect: [1580, 60, 940, 1240], min: false },
      { id: 103, title: 'desk_rig.blend — Blender', app: 'blender', rect: [2620, 220, 1800, 980], min: false },
      { id: 104, title: 'n2_capture.pcapng — Wireshark', app: 'wireshark', rect: [2700, 300, 1400, 800], min: true },
      { id: 105, title: 'Terminal — ollama serve', app: 'windowsterminal.exe', rect: [300, 900, 1100, 480], min: false },
    ];
    this.clip = [{ text: 'git commit -am "TABULA: depth touch band auto-tune"', t: Date.now() - 64e3 }, { text: 'ws://127.0.0.1:7777/ws', t: Date.now() - 300e3 }, { text: 'ngap && ngap.procedureCode == 15', t: Date.now() - 900e3 }];
    this.t0 = T.now();
  }
  static seedLines() {
    return ['# tabula_host.py — TABULA-Ω host bridge (simulated view)', 'import asyncio, json', 'from websockets.asyncio.server import serve', '', 'class TouchEngine:', '    """depth → touches (Wilson ITS 2010 band, DIRECT-style tip)"""', '    def __init__(self, band=(4.0, 14.0)):', '        self.band = band', '', '    def step(self, depth):', '        h = self.bg - depth', '        ...', '', 'async def main():', '    async with serve(handler, "127.0.0.1", 7777):', '        await asyncio.Future()'];
  }
  open() {
    this.emit({ t: 'welcome', v: 1, armed: true, host: { os: T.os, input: 'sim', focus: 'sim', capture: 'sim', sense: 'none', dry: true, sim: true, screens: this.screens, caps: ['act', 'ptr', 'touch', 'portal', 'win', 'clip', 'vlm', 'obs'] }, audit: { bind: 'in-page', tokenLen: 0, origin: 'n/a', sim: true } });
    this.pushFocus(); this.emit({ t: 'windows', list: this.wins }); this.emit({ t: 'clip', history: this.clip });
    this.emit({ t: 'obs', connected: true, scenes: ['Desk cam', 'Screen + cam', 'BRB', 'Overhead projector'], current: 'Screen + cam', sim: true });
    this.timers.push(setInterval(() => this.telemetry(), 1000));
    this.timers.push(setInterval(() => this.portalTick(), 1000 / 12));
    this.telemetry();
  }
  close() { this.timers.forEach(clearInterval); this.timers = []; }
  emit(m) { setTimeout(() => T.host._in(m), 0); }
  setFocus(i) { this.focusIdx = (i + T.SIM_APPS.length) % T.SIM_APPS.length; this.pushFocus(); }
  pushFocus() { const a = T.SIM_APPS[this.focusIdx]; this.emit(Object.assign({ t: 'focus', pid: 4200 + this.focusIdx, sim: true }, a)); }
  telemetry() {
    const t = (T.now() - this.t0) / 1000, s = (p, a) => 0.5 + 0.5 * Math.sin(t / p + a);
    this.emit({ t: 'telemetry', sim: true, cpu: 18 + 30 * s(7, 0) + 6 * Math.random(), mem: { used: 22.4 + 3 * s(40, 1), total: 64 },
      net: { rx: 1.2e6 * s(5, 2) + 2e4, tx: 3e5 * s(9, 1) + 1e4 },
      gpus: [0, 1, 2].map((i) => ({ index: i, name: 'SIM GPU ' + i, util: Math.round(100 * Math.max(0, s(3 + i, i) - 0.15 * i)), memUsed: 6 + 10 * s(20, i) + 4 * i, memTotal: [24, 16, 12][i], temp: 45 + 25 * s(10, i), power: 60 + 180 * s(4, i) })),
      ollama: [{ name: 'qwen2.5vl:7b (example)', vram: 7.9e9 }, { name: 'qwen3:32b (example)', vram: 21.3e9 }] });
  }
  send(m) {
    const reply = (x) => this.emit(Object.assign({ id: m.id }, x));
    switch (m.t) {
      case 'ping': this.emit({ t: 'pong', ts: m.ts, hts: Date.now() }); return true;
      case 'arm': this.emit({ t: 'armed', on: !!m.on }); reply({ t: 'ack', ok: true }); return true;
      case 'panic': this.emit({ t: 'armed', on: false, reason: 'panic (sim)' }); return true;
      case 'act': this.act(m.a); reply({ t: 'ack', ok: true, dry: true, out: this.lastOut || undefined }); this.lastOut = null; return true;
      case 'ptr': this.ptr(m); return true;
      case 'touch': return true;
      case 'portal': this.portal = m.op === 'stop' ? null : m; return true;
      case 'win': this.win(m); reply({ t: 'ack', ok: true, dry: true }); return true;
      case 'clip':
        if (m.op === 'set' || m.op === 'paste') { this.clip.unshift({ text: m.text, t: Date.now() }); this.clip = this.clip.slice(0, 30); this.emit({ t: 'clip', history: this.clip }); if (m.op === 'paste') this.typeText(m.text); }
        reply({ t: 'ack', ok: true, dry: true }); return true;
      case 'vlm': setTimeout(() => reply({ t: 'vlm', ok: true, sim: true, text: T.SimHost.vlmAnswer(m.mode, m.prompt) }), 650); return true;
      case 'sense': reply({ t: 'ack', ok: false, err: 'no depth sensor in simulation — run tabula_host.py --sense synthetic' }); return true;
      case 'hello': case 'cfg': reply({ t: 'ack', ok: true }); return true;
      default: reply({ t: 'ack', ok: false, err: 'unknown message ' + m.t }); return true;
    }
  }
  static vlmAnswer(mode, prompt) {
    if (mode === 'ocr') return 'TABULA-Ω CALIBRATION NOTE\nProjector: Epson EF-21, throw ratio 1.03\nImage 1000 × 562.5 mm at 1030 mm throw\nTouch band 4–14 mm above desk (Wilson 2010)\nRe-run Gray-code capture after moving the rig.';
    if (mode === 'explain') return '“throw ratio” = distance ÷ image width. At 1.03, a 1.0 m wide image needs the lens 1.03 m from the desk (or a fold mirror).';
    if (mode === 'translate') return 'NOTA DE CALIBRAÇÃO — Projetor Epson EF-21, razão de projeção 1,03; imagem 1000 × 562,5 mm; banda de toque 4–14 mm.';
    return 'Summary (simulated VLM): a calibration note for a desk projector — throw 1.03 m, touch band 4–14 mm, re-calibrate after moving the rig.';
  }
  act(a) {
    const ed = this.editor;
    switch (a.do) {
      case 'text': this.typeText(a.s); break;
      case 'key': {
        const c = T.chord.pick(a.c); const s = Array.isArray(c) ? c.join(',') : String(c || '');
        if (/^(mod|ctrl|cmd)\+s$/.test(s)) ed.flash = 1;
        else if (s === 'up') ed.caret.l = Math.max(0, ed.caret.l - 1);
        else if (s === 'down') ed.caret.l = Math.min(ed.lines.length - 1, ed.caret.l + 1);
        else if (s === 'enter') { ed.lines.splice(ed.caret.l + 1, 0, ''); ed.caret.l++; ed.caret.c = 0; }
        break;
      }
      case 'run':
        this.lastOut = a.id === 'ollama_ps' ? 'NAME                  SIZE    PROCESSOR    UNTIL\nqwen2.5vl:7b          7.9 GB  100% GPU     4 minutes from now   (SIM)' : a.id === 'nvidia_smi' ? 'GPU 0  SIM  41°C  P2  93W / 350W  7980MiB / 24576MiB  38%   (SIM)' : '(sim) ' + a.id + ' finished';
        break;
      case 'obs':
        if (a.req === 'SetCurrentProgramScene' && a.data) this.emit({ t: 'obs', connected: true, scenes: ['Desk cam', 'Screen + cam', 'BRB', 'Overhead projector'], current: a.data.sceneName, sim: true });
        break;
      default: break;
    }
  }
  typeText(s) {
    const ed = this.editor; const parts = String(s).split('\n');
    parts.forEach((p, i) => {
      if (i > 0) { ed.lines.splice(ed.caret.l + 1, 0, ''); ed.caret.l++; ed.caret.c = 0; }
      const L = ed.lines[ed.caret.l] || ''; ed.lines[ed.caret.l] = L.slice(0, ed.caret.c) + p + L.slice(ed.caret.c); ed.caret.c += p.length;
    });
  }
  ptr(m) {
    const ed = this.editor;
    if (m.op === 'rel') { this.cursor[0] = T.clamp(this.cursor[0] + m.dx, 0, 1279); this.cursor[1] = T.clamp(this.cursor[1] + m.dy, 0, 719); }
    if (m.op === 'move' || m.op === 'down' || m.op === 'click') {
      if (this.portal && this.portal.meta && m.x != null) { const r = this.portal.meta.rect; this.cursor = [(m.x - r[0]) / r[2] * 1280, (m.y - r[1]) / r[3] * 720]; }
    }
    if (m.op === 'down' || m.op === 'click') ed.ripples.push({ x: this.cursor[0], y: this.cursor[1], t: T.now(), btn: m.btn || 'left' });
    if (m.op === 'wheel') ed.scroll = T.clamp(ed.scroll + (m.dy || 0) * 3, 0, Math.max(0, ed.lines.length - 8));
  }
  win(m) {
    const w = this.wins.find((x) => x.id === m.id); if (!w) return;
    if (m.op === 'focus') { w.min = false; this.wins = [w, ...this.wins.filter((x) => x !== w)]; const i = T.SIM_APPS.findIndex((a) => a.exe === w.app); if (i >= 0) this.setFocus(i); }
    if (m.op === 'min') w.min = true;
    if (m.op === 'max') { const s = this.screens.find((s) => w.rect[0] + w.rect[2] / 2 >= s.x && w.rect[0] + w.rect[2] / 2 < s.x + s.w) || this.screens[0]; w.rect = [s.x, s.y, s.w, s.h]; w.min = false; }
    if (m.op === 'restore') w.min = false;
    if (m.op === 'close') this.wins = this.wins.filter((x) => x !== w);
    if (m.op === 'move' && m.rect) w.rect = m.rect.map(Math.round);
    this.emit({ t: 'windows', list: this.wins });
  }
  /* render a fake 1280×720 "window" and emit it as a portal frame */
  portalTick() {
    if (!this.portal) return;
    if (!this.canvas) { this.canvas = document.createElement('canvas'); this.canvas.width = 1280; this.canvas.height = 720; }
    const g = this.canvas.getContext('2d'), ed = this.editor, now = T.now();
    g.fillStyle = '#10151c'; g.fillRect(0, 0, 1280, 720);
    g.fillStyle = '#1a222d'; g.fillRect(0, 0, 1280, 34); g.fillStyle = '#8aa0b2'; g.font = '15px ui-monospace, Menlo, Consolas, monospace';
    g.fillText('tabula_host.py — tabula — Visual Studio Code   ·   SIMULATED WINDOW', 16, 22);
    g.fillStyle = '#0c1117'; g.fillRect(0, 34, 52, 686);
    g.font = '19px ui-monospace, Menlo, Consolas, monospace';
    const top = Math.floor(ed.scroll);
    for (let i = 0; i < 26; i++) {
      const li = top + i; if (li >= ed.lines.length) break; const y = 64 + i * 25;
      g.fillStyle = '#4a5a68'; g.fillText(String(li + 1).padStart(3), 8, y);
      const L = ed.lines[li];
      g.fillStyle = /^\s*#/.test(L) ? '#6a9955' : /\b(def|class|import|from|async|await|return|with)\b/.test(L) ? '#c586c0' : '#d4d4d4';
      g.fillText(L, 66, y);
      if (li === ed.caret.l && Math.floor(now / 500) % 2 === 0) { const w = g.measureText(L.slice(0, ed.caret.c)).width; g.fillStyle = '#aeafad'; g.fillRect(66 + w, y - 18, 2, 23); }
    }
    if (ed.flash > 0) { g.fillStyle = `rgba(124,240,255,${ed.flash * 0.35})`; g.fillRect(0, 34, 1280, 686); g.fillStyle = '#7cf0ff'; g.font = 'bold 28px system-ui'; g.fillText('SAVED', 1120, 700); ed.flash = Math.max(0, ed.flash - 0.08); }
    ed.ripples = ed.ripples.filter((r) => now - r.t < 700);
    for (const r of ed.ripples) { const k = (now - r.t) / 700; g.strokeStyle = r.btn === 'right' ? `rgba(255,92,147,${1 - k})` : `rgba(255,200,97,${1 - k})`; g.lineWidth = 3; g.beginPath(); g.arc(r.x, r.y, 10 + 40 * k, 0, 7); g.stroke(); }
    g.strokeStyle = '#ffffff'; g.lineWidth = 2; g.beginPath(); g.moveTo(this.cursor[0], this.cursor[1]); g.lineTo(this.cursor[0] + 12, this.cursor[1] + 16); g.lineTo(this.cursor[0] + 4, this.cursor[1] + 15); g.closePath(); g.stroke();
    const tgt = this.portal.target || {};
    const w = tgt.win ? this.wins.find((x) => x.id === tgt.win) : this.wins[0];
    const rect = w ? w.rect : [0, 0, 1280, 720];
    this.portal.meta = { rect };
    createImageBitmap(this.canvas).then((bmp) => { T.engine.dirty = true; T.bus.emit('host:frame', { hdr: { seq: 0, rect, w: 1280, h: 720, cursor: this.cursor, sim: true, title: w ? w.title : 'screen' }, bmp }); });
  }
};

/* ---------------- Web MIDI (browser → any MIDI port, incl. loopMIDI / IAC / ALSA virtual) ---------------- */
T.midi = {
  access: null, out: null, state: 'idle',
  async init() {
    if (this.access || this.state === 'pending') return !!this.access;
    if (!navigator.requestMIDIAccess) { this.state = 'unsupported'; return false; }
    this.state = 'pending';
    try { this.access = await navigator.requestMIDIAccess({ sysex: false }); this.state = 'ready'; this.pick(T.cfg.midi.outId); this.access.onstatechange = () => T.bus.emit('midi:ports'); T.bus.emit('midi:ports'); return true; }
    catch (e) { this.state = 'denied'; T.log.warn('midi', 'Web MIDI unavailable: ' + e.message); return false; }
  },
  outputs() { return this.access ? [...this.access.outputs.values()] : []; },
  pick(id) { const o = this.outputs(); this.out = o.find((x) => x.id === id) || o[0] || null; if (this.out) T.cfg.midi.outId = this.out.id; return this.out; },
  send(bytes) {
    if (this.out) { try { this.out.send(bytes); return true; } catch (e) { T.log.warn('midi', e.message); } }
    if (T.host.connected && T.host.armed) { T.host.send({ t: 'act', a: { do: 'midi', msg: bytes } }); return true; }
    return false;
  },
  cc(cc, val) { const ch = (T.cfg.midi.ch - 1) & 15; return this.send([0xb0 | ch, cc & 127, T.clamp(Math.round(val), 0, 127)]); },
  noteOn(n, vel = 100) { const ch = (T.cfg.midi.ch - 1) & 15; return this.send([0x90 | ch, n & 127, T.clamp(vel, 1, 127)]); },
  noteOff(n) { const ch = (T.cfg.midi.ch - 1) & 15; return this.send([0x80 | ch, n & 127, 0]); },
};

/* ---------------- action executor ---------------- */
T.actions = {
  describe(a) {
    if (!a) return '—';
    switch (a.do) {
      case 'key': return 'key ' + T.chord.pretty(a.c);
      case 'text': return 'type “' + String(a.s).replace(/\n/g, '⏎').slice(0, 40) + '”';
      case 'seq': return 'sequence (' + a.steps.length + ' steps)';
      case 'wheel': return 'wheel ' + (a.dy > 0 ? '▼' : '▲') + (a.mods ? ' +' + a.mods : '');
      case 'media': return 'media ' + a.op;
      case 'launch': return 'launch ' + a.id;
      case 'run': return 'run ' + a.id;
      case 'url': return 'open ' + a.href;
      case 'obs': return 'OBS ' + a.req + (a.data && a.data.sceneName ? ' → ' + a.data.sceneName : '');
      case 'midi': return 'MIDI ' + a.msg.map((b) => b.toString(16).padStart(2, '0')).join(' ');
      case 'ws': return 'workspace ' + a.name;
      case 'tool': return 'tool ' + a.name;
      case 'timer': return 'timer ' + a.min + ' min';
      default: return a.do;
    }
  },
  async run(a, ctx = {}) {
    if (!a) return;
    switch (a.do) {
      case 'seq': for (const s of a.steps) { await this.run(s, ctx); await T.sleep(s.wait ?? 70); } return;
      case 'ws': T.engine.setWorkspace(a.name); return;
      case 'tool': T.engine.activateTool(a.name); return;
      case 'timer': { const tw = T.engine.get('timer'); if (tw) tw.start(a.min * 60); T.bus.emit('toast', { text: `Timer ${a.min} min started`, kind: 'ok' }); return; }
      case 'macro': { const m = T.cfg.macros.find((x) => x.id === a.id); if (m) await this.run({ do: 'seq', steps: m.steps }, ctx); return; }
      case 'panic': T.host.panic('desk panic'); return;
      case 'midi': T.midi.send(a.msg); return;
      case 'wheel': T.host.ptr({ op: 'wheel', dy: a.dy || 0, dx: a.dx || 0, mods: a.mods || '' }); if (!T.host.armed) T.host.act(a); else T.log.act('act', this.describe(a)); return;
      default: return T.host.act(a);
    }
  },
};
