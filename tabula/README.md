# TABULA-Ω — projected desk

An interactive desk: a projector above the desk paints a user interface onto it, cameras and depth sensors see your fingers, hands, paper and physical tokens, and a small host program turns what happens on the desk into real input for your computer and its programs.

```
dist/tabula.html        the projected runtime + operator console (single file, no build step)
dist/tabula_host.py     the host bridge (single file): OS input, windows, capture, sensing, integrations
dist/tokens.svg         printable ArUco MIP 36h12 tokens at true scale (0–3 = image corners, 10+ = pucks)
src/  host/  build.py   the sources — python build.py regenerates dist/
tests/                  headless page smoke test, host↔page integration, dual-window test (host self-test is built in)
```

Keep `tabula.html` next to `tabula_host.py` (both are in `dist/`); the commands below run from that folder.

## Try it

* **No hardware:** open `tabula.html` in Chrome/Edge. It starts with a simulated host: click the desk preview as a finger (Shift-click pins a finger, Alt-drag pinches, Ctrl-drag is two fingers), drop a mug on the desk and watch widgets move out of its way, run the Gray-code calibration against the synthetic camera, read the TRIBUNAL.
* **On your machine:**

```bash
pip install websockets numpy opencv-contrib-python psutil "mss>=10" pillow
python tabula_host.py --dry-run --sense synthetic   # everything live, nothing injected
python tabula_host.py                               # real input; starts DISARMED
```

The host opens `http://127.0.0.1:7777/#t=<token>` in your browser (and prints the same link). The `#t=` fragment is this run's token: fragments never reach a server or a log, the page moves it into the tab's session storage and scrubs it from the address bar, and the page itself never contains it — so another program or user that fetches the page gets nothing it could drive your computer with. A new token is made every run; reopen the printed link after restarting the host. Press **Project here** (or **Projector window** for a second window on the projector screen — it inherits the token; with the Window Management API it goes fullscreen on the non-primary screen by itself). Exactly one window leads (runs the desk engine, owns the host link and the camera): a projector window outranks a console, and otherwise the window already leading keeps the lead — opening another tab never takes it over. Followers mirror the desk and forward clicks and commands.

Optional extras: Windows `pycaw dxcam`, Linux `evdev` (uinput) or `xdotool`/`wmctrl` (X11), macOS `pyobjc-framework-Quartz`, MIDI `mido python-rtmidi`, OCR `pytesseract`, depth SDKs `pyrealsense2`, `pyorbbecsdk2`, `pyk4a`, `pylibfreenect2`.

## Reference rig (SCHEME tab computes all of this for your hardware)

| Part | Default | Why |
|---|---|---|
| Projector | Optoma GT2000HDR, 3500 lm, throw 0.5, 100 % offset, 8.6 ms game-mode lag | 16.6 : 1 contrast at 300 lx on a 1.0 × 0.56 m image; lens 500 mm above the far edge, axis ⟂ desk, no keystone |
| Depth sensor | Orbbec Femto Bolt NFOV at 800 mm | footprint 1228 × 1019 mm covers the image; touch band ≈ 3–15 mm (Wilson 2010 scaled) |
| Touch option | 850 nm Class-1 line laser 1–2 mm above the desk + IR-pass camera | crisp touch-down (Epson/Xperia Touch method): `--sense lightplane:N` |
| Capture camera | 4K webcam near the lens | document OCR needs far more pixels than tracking |
| Surface | matte white / light grey, gain ≈ 1.0 | gloss throws a hotspot into your eyes |

Fold-mirror and angled mounts, other projectors (EF-21, LK830ST, LS630W, EV-110, Freestyle 2, MoGo 3 Pro) and sensors (RealSense D405/D435/D455, Kinect v2) are presets. Throw, mirror size, lux → contrast (AVIXA ISCR), mm/px, legible text height (16′/22′ with foreshortening), sensor footprint, touch band, latency budget and camera exposure multiples are all derived live, with side and plan drawings.

## Commissioning

1. **Mount** the projector with its axis perpendicular to the desk; switch it to game mode; turn its keystone and picture processing off (they add 30–100 ms and discard pixels).
2. **Corner pin** (CALIBRATE): drag the four handles until the frame sits on the desk area; the mm grid shows every 10 mm. Mesh 5×4 fixes lens/non-flat residue.
3. **Camera ↔ desk**: Gray-code (black, white, every bit-plane plus inverse → per-pixel decode → one correspondence per stripe cell → RANSAC homography + a fitted radial lens term). Webcam in the page, or *Gray-code the host camera* in LINK for the tangibles/scan camera. SIM CAM reports ground-truth error (≈ 0.05 mm).
4. **Sensor → desk**: LINK → *Tap-calibrate sensor → desk*: touch and hold nine rings.
5. **Accuracy test**: nine targets, 1–3 rounds. The mean offset is removed per sensor; the spread sets the safe target size the ERGONOMICS critic enforces.
6. **TRIBUNAL**: eight critics (optics, geometry, ergonomics, latency, sensing, safety, privacy, mount). Arming OS injection needs every critic to PASS or each WARN acknowledged; any FAIL blocks. Arm from the console or hold the SAFE pill on the desk for 2 s.

## What the desk does

Workspaces follow the focused program (or pick DEV / MAKE / STUDIO / PAPER / OPS): **palette** of the focused app's shortcuts (22 built-in profiles: VS Code, browsers, terminals, Blender, Photoshop, Krita, GIMP, Figma, OBS via WebSocket, Resolve, Premiere, Ableton, Wireshark with SIP/Diameter/GTPv2/PFCP/NGAP/NAS-5GS filter buttons, Office, media, files, calls, KiCad, FreeCAD) · **macro deck** · **trackpad** (ballistics, tap/2/3-finger clicks, double-tap-drag, natural 2-finger scroll, pinch zoom, 3-finger desktop swipes) · **portal** (stream any window/screen, touch it to operate that program; magnifier; real OS touch on Windows/Linux) · **dials + inertial jog** · **mixer** (faders → CC, velocity pads → notes, transport) over Web MIDI or host MIDI · **keys** (NAV/NUM/FN/QWERTY, sticky + locking modifiers) · **scan bay** (flash-lit capture → OCR/VLM → copy/type/explain/translate/pin; tap a word to explain it) · **ink** notes with handwriting → text · **ruler** (true scale, desk-wide distance/angle/area, A4 check) · **clipboard shelf** · **window map** (focus/move/flick max-min/close) · **system** (CPU, every NVIDIA GPU, Ollama's loaded models) · **timer** (anchors a ring around a mug) · **tangible pucks** (ArUco: rotate to scroll/volume/jog, place to switch workspace).

**Getting out of menus:** the **ESC** button sits on the rail at the top of the desk in every workspace. A tap sends one Esc — it closes the open menu, sub-menu, command palette, find bar, dropdown or dialog, one level per tap; hold it for ½ s to send Esc three times and back out of nested menus at once. Toggles such as Fullscreen or DevTools close with the same palette button that opened them. The KEYS widget and your keyboard's Esc work too.

Physical objects push widgets into free space (Desktopography). Callouts appear away from your hand (Vogel & Balakrishnan). Projection is dimmed on hands and blacked out on heads.

## Per-OS notes

* **Windows** — SendInput for keys/mouse (Unicode text, so any layout), `InjectTouchInput` for real multi-touch. Windows blocks injection into elevated windows unless the host runs elevated (UIPI). Launch entries are resolved with PATH/PATHEXT (`code` → `code.cmd`); VS Code, Blender and OBS are found in their default install folders, and OBS is started in its `bin\64bit` folder as it requires. Window moves compensate for the invisible resize borders, so a window keeps its size. MIDI: create a port named `TABULA` in loopMIDI / Windows MIDI Services.
* **Linux** — `evdev` + `/dev/uinput` works on X11 and Wayland (add a udev rule `KERNEL=="uinput", GROUP="input", MODE="0660"` and put yourself in `input`). uinput sends key *positions*, so typed text goes through the clipboard unless your first keyboard layout is US (detected from GNOME/KDE settings, `setxkbmap` or `localectl`; override with `keyboard_layout`). The virtual touchscreen spans the whole desktop; on Wayland with several monitors the compositor maps it to one output — map it to the desk's screen (e.g. sway `input … map_to_output`, GNOME Settings → Wacom/Touchscreen) or coordinates will be off. Focus detection: X11 (`xprop`), sway, Hyprland, KDE (`kdotool`), GNOME (the "Window Calls" extension). Without uinput, `xdotool` drives X11 (layout-aware typing).
* **macOS** — grant Accessibility (and Screen Recording for window titles/capture) to the terminal running the host. There is no public touch-injection API, so the portal falls back to mouse.

## ~/.tabula/config.json (created on first run)

`launch` and `run` are argv allow-lists, never a shell. An entry is an argv list or `{"argv": [...], "cwd": "..."}`. The host refuses — and the SAFETY critic fails on — shells or interpreters given inline code (`bash -lc`, `pwsh -enc`, `python -c`, `node -e`, `env sh -c`, `cmd /c` …), elevation (`sudo`, `runas` …), `mshta`/`rundll32`, and wildcards. `http` holds named requests, e.g. Home Assistant:

```json
"http": { "desk_light": { "method": "POST", "url": "http://homeassistant.local:8123/api/services/light/toggle",
          "headers": { "Authorization": "Bearer <long-lived token>" }, "json": { "entity_id": "light.desk" } } }
```

Other keys: `observe_disarmed` (default true: PORTAL, clipboard history and scan work while disarmed — they never change anything; set false to require arming), `clip_watch` (clipboard history; copies a password manager marks as concealed are always skipped, and entries that look like passwords or API keys are masked on the desk), `limits` (chords per action, characters per text/paste, wheel notches), `type_via` (`auto` · `keys` · `paste`), `extra_hosts` / `extra_origins` (LAN names allowed besides this PC's own), `allow_no_origin` (scripts without an Origin header; off), `allow_file_origin` (connect from `tabula.html` opened from disk; off), `deadman_s` (disarm when the arming window goes silent; 10), `touch_timeout_s` (a touch the page stops updating is lifted).

`vlm.chain` tries Ollama (`/api/chat`, default `qwen2.5vl:7b`), then an OpenAI-compatible server, then Anthropic (only with `allow_cloud: true` and `ANTHROPIC_API_KEY`; the PRIVACY critic warns), then Tesseract. `osc_targets`, `tuio_out`, `obs` (password), `sense` (band, hysteresis, One Euro), `calib` (stored homographies) live here too. Put `hand_landmarker.task` in `~/.tabula/models/` to run AIR hand tracking offline.

## Safety model

* **Who can talk to the host.** Loopback bind. A fresh 256-bit token per run that reaches only the browser the host opens — through a 0600 forwarding page in `~/.tabula`, so the token never appears on a command line (`ps`, `/proc/*/cmdline`) — and lives in that tab's session storage; the served page, `config.json`, page state and logs never contain it. Host-header and Origin allow-lists (DNS-rebinding guard) — in LAN mode (`--lan`) they list this PC's own names and addresses, and other devices pair with the LAN link the host prints or by pasting the token. LAN traffic is plain `ws://`: use LAN mode only on a network you trust. WebSocket clients without an Origin are refused, and `tabula.html` opened from disk (`Origin: null`, shared by every local file) only connects after you set `allow_file_origin: true`. `frame-ancestors 'none'` + `X-Frame-Options: DENY`, so no site can frame the desk and click through it. Windows of one run talk over a BroadcastChannel named after its token, so other pages cannot command the leading window.
* **What can inject.** The host starts disarmed. Arming needs a fresh, unanimous TRIBUNAL report — this protects against arming by accident, not against a program that holds the token (the host cannot re-run the page's critics; the token and the loopback bind are the boundary). One window arms at a time; once armed, only that window may send keys, pointer, touch, window operations or clipboard writes. TUIO input (`--sense tuio`) is a local UDP protocol without authentication: any program on this PC can send touches to the desk while it is enabled — they still act only through the desk's widgets.
* **Stopping.** PANIC and disarm are handled ahead of any queued or running work: typing stops within one 12-character chunk, a key sequence or wheel burst stops at the next step, queued input is answered as aborted, and every held key, button and touch (including modifiers of a Ctrl-wheel) is released. Every window has its own outbound queue, so a window that stops reading (sleeping laptop, frozen tab) is dropped after 4 s instead of delaying anyone's PANIC. A follower window's PANIC opens its own socket, so it works even when the leading window hangs. The host also disarms when the arming window closes or stops answering for 10 s (`deadman_s`), after 15 min idle, or when a flat palm lands on the desk. Watchdogs release a button held still for 15 s and lift a touch the page stops updating for 3 s.
* **Limits.** Per-type rate limits (releases are never limited or dropped), at most 32 chords / 4 000 typed or 200 000 pasted characters per action, bounded scan size, 2 MB page state.
* **Records.** `~/.tabula` is 0700 and its files 0600. The audit log (`audit.log`, JSON lines) records every action with typed or pasted text reduced to its length and a hash; log output redacts tokens even with `-v`. `--port`, `--lan` and `--tuio-out` apply to one run and are never written to `config.json`.
* **Dry run** (`--dry-run`) records every action and changes nothing: no input, no clipboard, no OSC, no OBS, no launches.

## Protocol (page ⇄ host, JSON over `/ws`)

Input messages (`act`, `ptr`, `touch`, window operations, `clip set`) are accepted only from the window that armed. `act {a:{do:key|text|paste|wheel|media|launch|run|url|obs|osc|midi|http}}` · `ptr {op:move|rel|down|up|click|wheel}` · `touch {contacts}` · `portal {op:start|stop, target:{follow|win|screen|magnify}}` · `win {op:list|focus|min|max|restore|close|move}` · `clip` · `vlm` · `sense {op:start|stop|background|tapcal|graycode}` · `arm` · `panic`. Host → page: `welcome`, `focus`, `windows`, `touches {contacts, hands, heads, objects, palm}`, `telemetry`, `clip`, `obs`, `gc`, `tapcal`, binary portal frames `[u32 header length][JSON header][JPEG]`.

## Tests

```bash
python tabula_host.py --selftest          # chords, allow-list/secret/layout policy, PANIC guard, TapCal lift, store perms,
                                          # TUIO robustness, homography/RANSAC, Gray code, OSC, One Euro, depth touch engine, ArUco, JPEG
python tests/smoke_page.py                # every tab; presses that span frames (palette, deck, keys, sticky modifiers, dials);
                                          # SIM CAM calibration, WebGL warp, zero JS errors
python tests/test_integration.py          # host --dry-run --sense synthetic ↔ page: no token in the page, framing refused,
                                          # Host/Origin/token checks, gate, input bound to the arming window, injection, touch
                                          # watchdog, limits, portal, PANIC aborting a running sequence, hostile page state,
                                          # redacted audit, CLI flags not persisted, LAN allow-list
python tests/test_dual_window.py          # console follows a projector window, RPC, handover, two consoles → one leader
```

The research behind every number is in the page's DOSSIER tab.
