/* ==========================================================================
   TABULA-Ω · window link — console ⇄ projector window over BroadcastChannel.
   Exactly one window is the LEADER (a #projector window if one is open,
   otherwise the console). Only the leader runs the engine, talks to the host
   and owns the camera; followers mirror it with preview frames + status and
   send their clicks and commands through a small RPC.
   ========================================================================== */
'use strict';

T.cfgVer = 0;
let cfgTimer = null;
T.setCfgDirty = () => {
  T.cfgVer = Date.now() * 1000 + ((T.cfgVer % 1000) + 1);
  if (T.engine) T.engine.dirty = true;
  clearTimeout(cfgTimer);
  cfgTimer = setTimeout(() => { const pub = T.cfgPublic(); T.saveCfg(); T.link.post({ k: 'cfg', cfg: pub, ver: T.cfgVer, from: T.link.id }); T.bus.emit('cfg:changed'); if (T.host.mode === 'live' && T.host.connected && T.link.isLeader()) T.host.send({ t: 'cfg', op: 'save', cfg: pub }); }, 120);
};

T.api = {
  pointer(a) { T.input.ev('sim', a.id, a.phase, a.x, a.y, a.extra || {}); },
  setWorkspace(a) { T.engine.setWorkspace(a.name, true); },
  setAuto(a) { T.engine.setAuto(!!a.on); },
  patchCfg(a) { T.deepMerge(T.cfg, a.patch); T.engine.layoutDirty = true; T.setCfgDirty(); },
  simFocus(a) { if (T.host.mode === 'sim' && T.host.link) T.host.link.setFocus(a.i); },
  simObjects(a) { T.engine.setSimObjects(a.list || []); },
  gray(a) { return T.calib.runGray(a); },
  grayCancel() { T.calib.cancel = true; },
  accStart(a) { T.calib.acc.start(a.rounds || 1); },
  accStop() { T.calib.acc.stop(); },
  latency() { return T.calib.latency(); },
  hostMode(a) { if (a.run) T.setRunToken(a.run); if (a.token) T.setRunToken(a.token); if (a.url != null && !T.BOOT) T.cfg.host.url = a.url; T.cfg.host.mode = a.mode; T.host.start(a.mode); T.setCfgDirty(); },
  hostArm(a) { return T.host.arm(!!a.on, a.gate); },
  panic(a) { T.host.panic((a && a.reason) || 'console PANIC'); },
  hostSend(a) { return T.host.send(a.msg); },
  hostRequest(a) { return T.host.request(a.msg, a.timeout || 8000); },
  airStart() { return T.air.start(); },
  airStop() { T.air.stop(); },
  async midiInit() { await T.midi.init(); return { state: T.midi.state, ports: T.midi.outputs().map((o) => ({ id: o.id, name: o.name })), out: T.midi.out ? T.midi.out.id : null }; },
  midiPick(a) { T.midi.pick(a.id); T.setCfgDirty(); return { out: T.midi.out ? T.midi.out.id : null }; },
  midiTest() { const ok = T.midi.noteOn(60, 100); setTimeout(() => T.midi.noteOff(60), 250); return { ok }; },
  replaceCfg(a) { const d = T.defaults(); T.cfg = T.deepMerge(d, a.cfg || {}); T.engine.layoutDirty = true; T.render.resize(); T.setCfgDirty(); return { ok: true }; },
  status() { return T.link.snapshot(); },
};
T.call = (m, a = {}) => (T.link.isLeader() ? Promise.resolve(T.api[m](a)) : T.link.rpc(m, a));

T.link = {
  id: 'w' + Math.random().toString(36).slice(2, 9), chan: null, peers: new Map(), role: T.isProjector ? 'projector' : 'console',
  leader: true, since: Date.now(), gone: new Set(), pending: new Map(), seq: 0, pvBmp: null, pvBusy: false, lastPv: 0, lastSt: 0, remote: null,
  /* The channel is named after this run's host token: only windows opened from the host's link (or given the token)
     can hear or command the leader. Any other page of the same origin — every local file shares file:// — cannot. */
  chanName() { return 'tabula-v2:' + (T.runToken || 'no-host'); },
  open() { try { this.chan = new BroadcastChannel(this.chanName()); this.chan.onmessage = (e) => this.on(e.data); } catch (e) { this.chan = null; } },
  rekey() { try { if (this.chan) this.chan.close(); } catch (e) { /* ignore */ } this.peers.clear(); this.open(); this.hb(); },
  init() {
    this.open(); if (!this.chan) return;
    setInterval(() => this.hb(), 400); this.hb();
    window.addEventListener('pagehide', () => this.post({ k: 'bye', id: this.id }));
    window.addEventListener('pageshow', (e) => { if (e.persisted) { this.id = 'w' + Math.random().toString(36).slice(2, 9); this.peers.clear(); this.hb(); } });   // back from bfcache: the old id said bye
    const fwd = (n) => T.bus.on(n, (d) => { if (this.leader && this.hasFollowers()) this.post({ k: 'evt', n, d }); });
    ['calib:progress', 'calib:done', 'calib:acc', 'calib:accdone', 'toast', 'panic'].forEach(fwd);
    T.bus.on('log', (e) => { if (this.leader && this.hasFollowers() && !e.remote) this.post({ k: 'evt', n: 'log', d: e }); });
  },
  post(m) { if (this.chan) { try { this.chan.postMessage(m); } catch (e) { /* uncloneable */ } } },
  hasFollowers() { return this.peers.size > 0; },
  hb() {
    const now = Date.now();
    // a silent follower is forgotten after 3 s; a silent LEADER only after 6 s — a tab loading next to it can block its thread for
    // seconds, and a premature takeover would drop the host link (and disarm). A frozen leader that comes back keeps the lead.
    for (const [id, p] of this.peers) if (now - p.t > (p.lead ? 6000 : 3000)) this.peers.delete(id);
    const want = this.computeLeader(), was = this.leader;
    if (!want) { this.leadSince = 0; this.leader = false; }
    else if (!was) {
      this.leadSince = this.leadSince || now;
      const nobodyLeads = ![...this.peers.values()].some((p) => p.lead);
      if (nobodyLeads || now - this.leadSince > 1200 || this.byeSeen) { this.leader = true; this.byeSeen = false; }   // take over only once it is clearly gone
    }
    if (this.leader && !was) this.since = now;
    this.post({ k: 'hb', id: this.id, role: this.role, t: now, lead: this.leader, since: this.since });
    if (was !== this.leader) { T.log.info('link', this.leader ? 'this window leads (engine + host + camera)' : 'following the ' + (this.leaderPeer() || 'other') + ' window'); T.bus.emit('link:role', this.leader); }
  },
  /* Exactly one leader: projector windows outrank consoles; among equals an incumbent keeps the lead (the one that
     has led longest, then the lower id), otherwise the lowest id takes it. A fresh window therefore never steals
     the lead from a console that is already driving the desk. */
  computeLeader() {
    const rank = (r) => (r === 'projector' ? 2 : 1), mine = rank(this.role);
    const peers = [...this.peers.entries()];
    if (peers.some(([, p]) => rank(p.role) > mine)) return false;
    const rivals = peers.filter(([, p]) => rank(p.role) === mine), leading = rivals.filter(([, p]) => p.lead);
    if (leading.length) return this.leader && leading.every(([id, p]) => (p.since || 0) > this.since || ((p.since || 0) === this.since && id > this.id));
    if (this.leader) return true;                               // nobody else leads: the incumbent keeps it (no id contest)
    return rivals.every(([id]) => id > this.id);
  },
  leaderPeer() { const l = [...this.peers.values()].find((p) => p.lead); return l ? l.role : null; },
  isLeader() { return this.leader; },
  rpc(m, a) {
    const id = this.id + ':' + (++this.seq);
    return new Promise((res) => { const to = setTimeout(() => { this.pending.delete(id); res({ ok: false, err: 'leader did not answer' }); }, m === 'gray' ? 120000 : 15000); this.pending.set(id, (r) => { clearTimeout(to); res(r); }); this.post({ k: 'rpc', id, m, a, from: this.id }); });
  },
  async on(m) {
    if (!m || m.from === this.id) return;
    switch (m.k) {
      case 'hb': { if (this.gone.has(m.id)) break;                 // a window that said bye may still fire one last heartbeat
        const isNew = !this.peers.has(m.id); this.peers.set(m.id, { role: m.role, t: Date.now(), lead: !!m.lead, since: m.since || 0 }); if ((isNew && m.role === 'projector' && this.role !== 'projector') || (m.lead && this.leader)) this.hb(); break; }
      case 'bye': this.peers.delete(m.id); this.gone.add(m.id); this.byeSeen = true; this.hb(); break;
      case 'cfg': if (m.ver > T.cfgVer && m.cfg && typeof m.cfg === 'object') { T.cfg = m.cfg; if (T.cfg.host) delete T.cfg.host.token; T.cfgVer = m.ver; T.saveCfg(); T.engine.layoutDirty = true; T.bus.emit('cfg:changed', 'remote'); } break;
      case 'rpc': if (this.leader && T.api[m.m]) { let r; try { r = await T.api[m.m](m.a || {}); } catch (e) { r = { ok: false, err: e.message }; } this.post({ k: 'rpc-r', id: m.id, r: r === undefined ? { ok: true } : r, to: m.from }); } break;
      case 'rpc-r': if (m.to === this.id && this.pending.has(m.id)) { const f = this.pending.get(m.id); this.pending.delete(m.id); f(m.r); } break;
      case 'evt': if (!this.leader) { if (m.n === 'log') { const e = Object.assign({}, m.d, { remote: true }); T.log.buf.push(e); if (T.log.buf.length > T.log.max) T.log.buf.shift(); T.bus.emit('log', e); } else T.bus.emit(m.n, m.d); } break;
      case 'pv': if (!this.leader && m.blob) { try { const b = await createImageBitmap(m.blob); if (this.pvBmp && this.pvBmp.close) this.pvBmp.close(); this.pvBmp = b; this.pvFresh = true; } catch (e) { /* ignore */ } } break;
      case 'st': if (!this.leader) this.applyStatus(m.st); break;
      default: break;
    }
  },
  snapshot() {
    const h = T.host;
    return {
      host: { mode: h.mode, connected: h.connected, armed: h.armed, info: h.info, focus: h.focus, windows: h.windows, screens: h.screens, telemetry: h.telemetry, clip: h.clip, obs: h.obs, rtt: h.rtt, audit: h.audit },
      engine: { ws: T.engine.ws, auto: T.engine.auto, profile: T.engine.profile && T.engine.profile.id, fps: T.engine.stats.fps, p95: T.engine.frameP95(), sim: T.engine.simObjects, targets: T.engine.targets().map((t) => ({ x: t.x, y: t.y, w: t.w, h: t.h, label: t.label })), minFont: T.gfx.minFont },
      contacts: [...T.input.contacts.values()].map((c) => ({ key: c.key, src: c.src, x: c.x, y: c.y })),
      air: { on: T.air.on, fps: T.air.fps, err: T.air.err },
    };
  },
  applyStatus(st) {
    this.remote = st; Object.assign(T.host, st.host);
    T.engine.ws = st.engine.ws; T.engine.auto = st.engine.auto; T.engine.profile = T.allProfiles().find((p) => p.id === st.engine.profile) || T.PROFILES[0];
    T.engine.stats.fps = st.engine.fps; T.engine.simObjects = st.engine.sim || []; T.engine.remoteTargets = st.engine.targets; T.gfx.minFont = st.engine.minFont;
    T.air.on = st.air.on; T.air.fps = st.air.fps; T.air.err = st.air.err;
  },
  /* leader duties each frame */
  tick(now) {
    if (!this.leader || !this.hasFollowers()) return;
    if (now - this.lastSt > 450) { this.lastSt = now; this.post({ k: 'st', st: this.snapshot() }); }
    if (!this.pvBusy && now - this.lastPv > 120) {
      this.pvBusy = true; this.lastPv = now;
      if (!this._pc) this._pc = document.createElement('canvas');
      const c = this._pc, w = 960, h = Math.round(960 * T.render.texH / T.render.texW); c.width = w; c.height = h;
      c.getContext('2d').drawImage(T.render.surface, 0, 0, w, h);
      c.toBlob((b) => { this.pvBusy = false; if (b) this.post({ k: 'pv', blob: b }); }, 'image/jpeg', 0.72);
    }
  },
};
