/* ==========================================================================
   TABULA-Ω · TRIBUNAL — eight adversarial critics audit the live rig. Each
   probes something concrete (numbers, layout, host policy). Arming OS input
   injection needs unanimous consensus: every critic PASS, or its WARN
   individually acknowledged by the operator. Any FAIL is a hard block.
   ========================================================================== */
'use strict';

T.tribunal = {
  critics: [
    { id: 'optics', name: 'OPTICS', role: 'brightness, contrast, pixels',
      judge(x) {
        const r = x.r, N = [];
        if (r.iscr < 3) N.push(['FAIL', `Contrast ${r.iscr.toFixed(1)}:1 is below the 3:1 floor for any text (HFES 100).`, `Need ≥ ${Math.round(r.need(7))} lm for 7:1 at ${x.cfg.scheme.ambient} lx, or dim the room.`]);
        else if (r.iscr < 7) N.push(['WARN', `Contrast ${r.iscr.toFixed(1)}:1 — below passive-viewing 7:1 (AVIXA ISCR).`, `≥ ${Math.round(r.need(7))} lm, lower ambient to ${Math.round(r.E / 6)} lx, or accept dim UI.`]);
        else if (r.iscr < 15) N.push(['PASS', `Contrast ${r.iscr.toFixed(1)}:1 (passive viewing). Decision-grade 15:1 needs ${Math.round(r.need(15))} lm.`]);
        else N.push(['PASS', `Contrast ${r.iscr.toFixed(1)}:1 — ${r.cls}.`]);
        if (r.pitch > 0.8) N.push(['WARN', `${r.pitch.toFixed(2)} mm per pixel: 16′ text is only ${r.leg[0].px.toFixed(1)} px tall.`, 'Use a higher-resolution projector or a smaller image.']);
        if (r.expo.seq) N.push(['PASS', `DLP sequential colour: camera exposure must be a multiple of ${r.expo.projFrame.toFixed(2)} ms (common with ${x.cfg.scheme.mains} Hz lighting: ${r.expo.common.toFixed(1)} ms).`]);
        return N;
      } },
    { id: 'geometry', name: 'GEOMETRY', role: 'warp + camera registration',
      judge(x) {
        const N = [], c = x.cfg.output.corners;
        if (!T.geom.isConvexQuad(c)) N.push(['FAIL', 'Corner-pin quad is not convex — the warp folds over itself.', 'Reset corners in CALIBRATE.']);
        const H = T.cornerH(); const Hi = H && T.m3.inv(H);
        if (!H || !Hi) N.push(['FAIL', 'Corner homography is singular.', 'Reset corners.']);
        else {
          let e = 0; for (const [s, t] of [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]) { const p = T.m3.apply(H, s, t), q = T.m3.apply(Hi, p[0], p[1]); e = Math.max(e, Math.hypot(q[0] - s, q[1] - t)); }
          if (e > 1e-6) N.push(['FAIL', `Warp round-trip error ${e.toExponential(1)} (numerically unstable).`, 'Re-seat the corners.']);
          else N.push(['PASS', `Warp round-trip exact (${e.toExponential(0)}), condition ${T.m3.cond(H).toFixed(1)}.`]);
          const area = Math.abs(T.geom.polyArea(c));
          if (area < 0.6) N.push(['WARN', `Image uses only ${(area * 100).toFixed(0)} % of projector pixels — digital shrink wastes resolution.`, 'Move/zoom the projector optically first; warp the remainder.']);
        }
        const k = x.cfg.calib;
        if (!k.H_desk_cam) N.push(['WARN', 'No camera ↔ desk calibration yet (only needed for AIR, SCAN and latency).', 'Run Gray-code in CALIBRATE.']);
        else if (k.rmsMm > 3) N.push(['FAIL', `Camera registration RMS ${k.rmsMm.toFixed(2)} mm is too coarse for touch.`, 'Re-run with finer stripes, locked exposure, dimmer room.']);
        else if (k.rmsMm > 1.2) N.push(['WARN', `Camera registration RMS ${k.rmsMm.toFixed(2)} mm (target < 1 mm).`, 'Re-run Gray-code; check focus.']);
        else N.push(['PASS', `Camera registration ${k.rmsMm.toFixed(2)} mm RMS via ${k.method}` + (k.truthMm != null ? ` (ground truth ${k.truthMm.toFixed(2)} mm)` : '') + '.']);
        const ar = x.r.W / x.r.H, dar = x.cfg.desk.w / x.cfg.desk.h;
        if (Math.abs(ar - dar) / ar > 0.02) N.push(['WARN', `Desk surface ${x.cfg.desk.w}×${x.cfg.desk.h.toFixed(0)} mm does not match the projector aspect (${x.r.W}×${x.r.H.toFixed(0)}).`, 'Apply the scheme aspect in SCHEME.']);
        return N;
      } },
    { id: 'ergonomics', name: 'ERGONOMICS', role: 'targets, text, handedness',
      judge(x) {
        const N = [], min = Math.max(x.cfg.desk.minTarget, x.cfg.calib.accuracy ? x.cfg.calib.accuracy.minTarget : 0);
        const tg = x.targets.filter((t) => !/^window /.test(t.label));
        const small = tg.filter((t) => Math.min(t.w, t.h) < min - 0.01);
        const tiny = tg.filter((t) => Math.min(t.w, t.h) < 10);
        if (tiny.length) N.push(['FAIL', `${tiny.length} targets under 10 mm (e.g. ${tiny[0].label} ${Math.min(tiny[0].w, tiny[0].h).toFixed(1)} mm).`, 'Enlarge the slot or the desk image.']);
        else if (small.length) N.push(['WARN', `${small.length}/${tg.length} targets below ${min.toFixed(0)} mm (e.g. ${small[0].label} ${Math.min(small[0].w, small[0].h).toFixed(1)} mm).`, 'OmniTouch: 16 mm for 95 % hits on flat surfaces.']);
        else N.push(['PASS', `All ${tg.length} targets ≥ ${min.toFixed(0)} mm` + (x.cfg.calib.accuracy ? ' (from your measured spread)' : ' (OmniTouch 95 % size)') + '.']);
        const kb = T.engine.kbRect();
        if (kb) { const hit = tg.filter((t) => T.geom.rectOverlap(t, kb) > 1); if (hit.length) N.push(['WARN', `${hit.length} targets overlap the keyboard mask.`, 'Move the mask or switch workspace.']); }
        const minFont = T.gfx.minFont === Infinity ? T.TYPE.min : T.gfx.minFont, capMin = minFont * T.TYPE.capRatio;
        if (capMin + 0.01 < x.r.leg[0].mm) N.push(['FAIL', `Smallest text ${capMin.toFixed(1)} mm cap < 16′ minimum ${x.r.leg[0].mm.toFixed(1)} mm at ${x.cfg.scheme.viewDist} mm / ${x.cfg.scheme.viewElev}°.`, 'Raise the type scale or sit closer.']);
        else if (T.TYPE.body * T.TYPE.capRatio + 0.01 < x.r.leg[1].mm) N.push(['WARN', `Body text ${(T.TYPE.body * T.TYPE.capRatio).toFixed(1)} mm cap is under the 22′ comfort size (${x.r.leg[1].mm.toFixed(1)} mm).`, 'Readable, but fatiguing for long sessions.']);
        else N.push(['PASS', `Text meets 16′ minimum and 22′ comfort at ${x.cfg.scheme.viewDist} mm, ${x.cfg.scheme.viewElev}° elevation.`]);
        N.push(['PASS', `${x.cfg.desk.handed}-handed layout; callouts placed away from the hand (Vogel & Balakrishnan 2010).`]);
        return N;
      } },
    { id: 'latency', name: 'LATENCY', role: 'end-to-end budget',
      judge(x) {
        const N = [], tot = x.r.total, meas = x.cfg.calib.latencyMs, p95 = T.engine.frameP95();
        if (tot > 150) N.push(['FAIL', `Estimated ${tot.toFixed(0)} ms touch→photon — taps will feel broken.`, 'Game-mode projector, faster sensor, disable projector keystone.']);
        else if (tot > 69) N.push(['WARN', `Estimated ${tot.toFixed(0)} ms > 69 ms tap-perception threshold (Deber 2015).`, 'Prediction is on for drags; prefer a projector with game-mode lag < 20 ms.']);
        else N.push(['PASS', `Estimated ${tot.toFixed(0)} ms ≤ 69 ms tap threshold (drags remain visible above 11 ms; prediction ${x.cfg.input.predictMs} ms).`]);
        if (meas != null) N.push([meas > 120 ? 'WARN' : 'PASS', `Measured projector→camera ${meas.toFixed(0)} ms.`]);
        if (p95 > 33) N.push(['WARN', `Render p95 frame ${p95.toFixed(1)} ms (< 60 fps).`, 'Close heavy widgets or lower projector resolution.', 'live']);
        if (T.host.connected && T.host.rtt != null) N.push([T.host.rtt > 20 ? 'WARN' : 'PASS', `Host round-trip ${T.host.rtt.toFixed(1)} ms.`, undefined, 'live']);
        return N;
      } },
    { id: 'sensing', name: 'SENSING', role: 'sensor geometry + accuracy',
      judge(x) {
        const r = x.r, N = [];
        if (!r.inRange) N.push(['FAIL', `${r.S.name} at ${r.sensorH} mm is outside its range ${r.S.range[0]}–${r.S.range[1]} m.`, 'Move the sensor or pick another preset.']);
        if (!r.covers) N.push(['WARN', `Footprint ${r.fp[0].toFixed(0)}×${r.fp[1].toFixed(0)} mm does not cover the ${r.W}×${r.H.toFixed(0)} mm image.`, 'Raise the sensor or use a wider FOV mode.']);
        else N.push(['PASS', `Footprint covers the image; ${r.depthPx.toFixed(1)} mm per depth pixel.`]);
        if (r.band) N.push(['PASS', `Touch band ${r.band.lo.toFixed(0)}–${r.band.hi.toFixed(0)} mm above the desk (Wilson 2010 scaled to ${r.sensorH} mm); worst-case error ≈ ${r.acc.toFixed(0)} mm.`]);
        const a = x.cfg.calib.accuracy;
        if (!a) N.push(['WARN', 'No measured touch accuracy yet.', 'Run the 9-target accuracy test in CALIBRATE.']);
        else N.push([a.r95 > 12 ? 'WARN' : 'PASS', `Measured ${a.src} R95 ${a.r95.toFixed(1)} mm after removing a ${Math.hypot(a.bias[0], a.bias[1]).toFixed(1)} mm systematic offset (n=${a.n}).`]);
        if (/ToF/.test(r.S.kind)) N.push(['PASS', 'ToF at 850 nm: run one sensor per desk (multi-ToF units interfere unless synced).']);
        return N;
      } },
    { id: 'safety', name: 'SAFETY', role: 'eyes, host exposure, kill paths',
      judge(x) {
        const N = [], r = x.r, rg = r.P.rg || '';
        if (/RG3/.test(rg)) N.push(['FAIL', 'RG3 projectors must not be used at a desk (hazard zone rules, installer only).', 'Use an RG1/RG2 unit.']);
        else if (r.eyeInBeam) N.push(['WARN', `A seated eye sits inside the beam (lens ${r.eyeToLens.toFixed(0)} mm away) — you would look straight into ${rg}.`, 'Move the lens over the far edge (100 % offset) or raise it; keep the head guard on.']);
        else N.push(['PASS', `${r.P.name}: ${rg}; a seated eye is outside the beam, lens ≈ ${r.eyeToLens.toFixed(0)} mm away.`]);
        if (!x.cfg.output.headGuard) N.push(['WARN', 'Head guard is off — a leaning head gets projected light in the eyes.', 'Enable it in CALIBRATE → Output.']);
        const au = T.host.audit;
        if (T.host.mode === 'sim') N.push(['PASS', 'Simulated host: nothing is injected into the OS.']);
        else if (!T.host.connected) N.push(['WARN', 'Host offline — cannot audit its policy.', 'Start tabula_host.py.']);
        else if (au) {
          if (au.bind && !/^(127\.|::1|localhost)/.test(au.bind) && !au.lan) N.push(['FAIL', `Host listens on ${au.bind} without LAN mode.`, 'Bind 127.0.0.1.']);
          else N.push([au.lan ? 'WARN' : 'PASS', `Host bound to ${au.bind}${au.lan ? ' (LAN mode: Host/Origin limited to this PC\'s own names; other devices pair with the #t= link the host prints)' : ''}.`, au.lan ? 'Leave LAN mode off unless a tablet must reach the desk.' : undefined]);
          if ((au.tokenLen || 0) < 24) N.push(['FAIL', 'Host token shorter than 24 chars.', 'Restart the host to regenerate.']);
          if (au.shellWildcard) N.push(['FAIL', 'The launch/run allow-list can run arbitrary code: ' + ((au.allowlist || []).join('; ') || 'shell, interpreter with inline code, elevation or wildcard') + '.', 'List exact argv arrays of programs, never a shell, interpreter one-liner or sudo.']);
          if (au.origins) N.push(['PASS', `${au.origins}; ${au.tokenDelivery || 'per-run token'}; framing refused${au.inputBinding ? '; ' + au.inputBinding : ''}.`]);
          if (au.allowNoOrigin) N.push(['WARN', 'Host accepts WebSocket clients without an Origin header.', 'Set allow_no_origin false unless a script needs it.']);
          if (au.idleDisarmS) N.push(['PASS', `Auto-disarm after ${au.idleDisarmS} s idle; PANIC is handled ahead of queued work and stops typing mid-string; flat palm disarms.`]);
          if (au.gate) N.push(['PASS', 'This report is advisory to the host: it checks freshness and unanimity, not the physics — the token and loopback bind are the security boundary.']);
        }
        return N;
      } },
    { id: 'privacy', name: 'PRIVACY', role: 'where camera pixels go',
      judge(x) {
        const N = [], v = T.host.info && T.host.info.vlm;
        if (!v) N.push(['PASS', T.host.mode === 'sim' ? 'Simulated VLM — no pixels leave the page.' : 'No VLM configured on the host.']);
        else if (v.cloud) N.push(['WARN', `OCR/VLM falls back to a cloud API (${v.provider}) — desk images leave this machine.`, 'Prefer a local model (Ollama) or disable the fallback.']);
        else N.push(['PASS', `VLM is local (${v.provider} · ${v.model}).`]);
        N.push(['PASS', 'Scan flashes the bay white before capture, so projected UI never reaches the VLM (ProCap lesson).']);
        if (T.host.info && T.host.info.persistFrames) N.push(['WARN', 'Host saves camera frames to disk.', 'Disable frame persistence.']);
        return N;
      } },
    { id: 'mount', name: 'MOUNT', role: 'orientation, heat, mirror',
      judge(x) {
        const N = [], r = x.r;
        if (r.lamp && !r.fold) N.push(['FAIL', 'Lamp projectors are limited to about ±15° tilt; pointing down shortens lamp life drastically.', 'Use a laser/LED unit or a fold mirror.']);
        else N.push(['PASS', `${r.P.name} orientation: ${r.P.orient}.`]);
        if (r.fold) N.push(['PASS', `Fold mirror ${Math.ceil(r.mirror.wM)}×${Math.ceil(r.mirror.LM)} mm (incl. 15 % margin), orientation ${r.mirror.good}; image is mirrored — use Rear/Ceiling mode or flip in OUTPUT.`]);
        if (r.tilt && r.key) N.push(['WARN', `Tilted mount needs ~${r.key.alpha.toFixed(0)}° keystone and keeps only ${(r.key.usable * 100).toFixed(0)} % of pixel rows.`, 'Mount the lens axis perpendicular to the desk.']);
        N.push(['PASS', 'Keep 50 cm clear at intake and exhaust; aim exhaust away from the mirror and cameras (heat shimmer).']);
        return N;
      } },
  ],
  run() {
    const r = T.scheme.compute(T.cfg), targets = T.engine.targets();
    const x = { cfg: T.cfg, r, targets };
    const out = this.critics.map((c) => {
      let notes; try { notes = c.judge(x); } catch (e) { notes = [['FAIL', 'critic crashed: ' + e.message]]; }
      const v = notes.some((n) => n[0] === 'FAIL') ? 'FAIL' : notes.some((n) => n[0] === 'WARN') ? 'WARN' : 'PASS';
      // an ack covers the finding, not today's decimals; 'live' notes (frame time, round trip) flicker with load and never re-close the gate
      const sig = notes.filter((n) => n[0] !== 'PASS' && n[3] !== 'live').map((n) => n[1].replace(/[-+]?\d[\d.,]*/g, '#')).join('|');
      const acked = v === 'WARN' && T.cfg.tribunal.acks[c.id] === sig;
      return { id: c.id, name: c.name, role: c.role, v, notes, acked, sig };
    });
    this.last = out; return out;
  },
  ack(id, on) { const v = (this.last || this.run()).find((c) => c.id === id); if (!v) return; if (on) T.cfg.tribunal.acks[id] = v.sig; else delete T.cfg.tribunal.acks[id]; T.setCfgDirty(); },
  gate() {
    const out = this.run(), fails = out.filter((c) => c.v === 'FAIL'), unacked = out.filter((c) => c.v === 'WARN' && !c.acked);
    const open = !fails.length && (!T.cfg.tribunal.strict || !unacked.length);
    const why = fails.length ? fails.map((c) => c.name).join(', ') + ' FAIL' : unacked.length ? unacked.map((c) => c.name).join(', ') + ' WARN not acknowledged' : '';
    return { open, why, report: { verdicts: out.map((c) => ({ id: c.id, v: c.v, acked: c.acked })), strict: T.cfg.tribunal.strict, at: Date.now() } };
  },
};
