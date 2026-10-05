/* ==========================================================================
   TABULA-Ω · config — defaults, hardware presets (researched), app profiles,
   workspaces, macros. Everything here is data; behaviour lives elsewhere.
   ========================================================================== */
'use strict';

/* ---------- projector presets (numbers from vendor pages / ProjectorCentral reviews, see DOSSIER) ---------- */
T.PROJECTORS = {
  'epson-ef21': { name: 'Epson EF-21 / EF-22', tech: '3LCD laser', lm: 1000, tr: [1.03, 1.03], res: [1920, 1080], lag: 80, lagEst: true, offset: 0, rg: 'RG2', orient: 'any angle (no limit)', color: 'simultaneous RGB (camera-friendly)', src: 'projectorcentral.com/epson-epiqvision_mini_ef-21.htm' },
  'optoma-gt2000hdr': { name: 'Optoma GT2000HDR', tech: 'DLP laser-phosphor', lm: 3500, tr: [0.5, 0.5], res: [1920, 1080], lag: 8.6, offset: 100, rg: 'RG2', orient: '360°', color: 'sequential (DLP banding)', src: 'projectorcentral.com/optoma-gt2000hdr.htm' },
  'benq-lk830st': { name: 'BenQ LK830ST', tech: 'DLP laser 4K', lm: 4000, tr: [0.5, 0.5], res: [3840, 2160], lag: 16, lagEst: true, offset: 100, rg: 'RG2', orient: '360° + portrait', color: 'sequential (DLP banding)', src: 'benq.com/en-us/business/projector/lk830st.html' },
  'viewsonic-ls630w': { name: 'ViewSonic LS630W', tech: 'DLP laser WXGA', lm: 4500, tr: [1.18, 1.54], res: [1280, 800], lag: 16, lagEst: true, offset: 100, rg: 'RG2', orient: '360° + portrait', color: 'sequential (DLP banding)', src: 'thinkedu.com (LS630W listing)' },
  'epson-ev110': { name: 'Epson EV-110', tech: '3LCD laser WXGA', lm: 2200, tr: [1.38, 2.19], res: [1280, 800], lag: 50, lagEst: true, offset: 0, rg: 'RG2', orient: 'any (lighting projector)', color: 'simultaneous RGB (camera-friendly)', src: 'adorama.com/ieslsev110.html' },
  'samsung-freestyle2': { name: 'Samsung Freestyle 2nd Gen', tech: 'LED DLP', lm: 230, tr: [1.2, 1.2], res: [1920, 1080], lag: 60, lagEst: true, offset: 0, rg: 'RG1', orient: '180° cradle', color: 'sequential (DLP banding)', src: 'projectorcentral.com/samsung-freestyle_2nd_gen.htm' },
  'xgimi-mogo3pro': { name: 'XGIMI MoGo 3 Pro', tech: 'LED DLP 960×540 (XPR)', lm: 422, tr: [1.2, 1.2], trEst: true, res: [960, 540], lag: 71, offset: 0, rg: 'RG1', orient: '130° rotation', color: 'sequential (DLP banding)', src: 'laurentwillen.com MoGo 3 Pro review' },
  'custom': { name: 'Custom projector', tech: 'custom', lm: 2000, tr: [0.8, 0.8], res: [1920, 1080], lag: 30, offset: 0, rg: 'RG2', orient: 'check manual', color: '—', src: 'user' },
};

/* ---------- sensor presets ---------- */
T.SENSORS = {
  'femto-bolt-nfov': { name: 'Orbbec Femto Bolt · NFOV unbinned', kind: 'ToF', res: [640, 576], fov: [75, 65], range: [0.5, 3.86], fps: 30, nm: 850, sdk: 'pyorbbecsdk2 / pyk4a (K4A wrapper)', src: 'orbbec.com Femto Bolt hardware specifications' },
  'femto-bolt-wfov': { name: 'Orbbec Femto Bolt · WFOV unbinned', kind: 'ToF', res: [1024, 1024], fov: [120, 120], range: [0.25, 2.21], fps: 15, nm: 850, sdk: 'pyorbbecsdk2', src: 'orbbec.com Femto Bolt hardware specifications' },
  'realsense-d435': { name: 'RealSense D435', kind: 'active IR stereo', res: [848, 480], fov: [87, 58], range: [0.28, 3.0], fps: 90, nm: 850, sdk: 'pyrealsense2', src: 'realsenseai.com D435 page' },
  'realsense-d405': { name: 'RealSense D405 (close range)', kind: 'stereo', res: [848, 480], fov: [87, 58], range: [0.07, 0.5], fps: 90, nm: 0, sdk: 'pyrealsense2', src: 'realsenseai.com (vendor range)' },
  'realsense-d455': { name: 'RealSense D455', kind: 'active IR stereo', res: [848, 480], fov: [87, 58], range: [0.52, 6.0], fps: 90, nm: 850, sdk: 'pyrealsense2', src: 'realsenseai.com (vendor range)' },
  'kinect-v2': { name: 'Kinect v2 (used market)', kind: 'ToF', res: [512, 424], fov: [70.6, 60], range: [0.5, 4.5], fps: 30, nm: 827, sdk: 'pylibfreenect2', src: 'DIRECT (Xiao 2016) setup; libfreenect2' },
  'webcam-1080p': { name: 'RGB webcam 1080p (AIR / pinch mode)', kind: 'RGB', res: [1920, 1080], fov: [70, 43], range: [0.3, 3], fps: 30, nm: 0, sdk: 'browser getUserMedia + MediaPipe', src: 'generic' },
  'ir-lightplane': { name: 'IR light plane + 850 nm-pass camera', kind: 'IR curtain', res: [1280, 720], fov: [90, 60], range: [0.3, 1.5], fps: 60, nm: 850, sdk: 'tabula_host --sense lightplane:N', src: 'Epson ELPFT01 method; NUI-Group LLP' },
};

/* ---------- workspaces: slot → widget kind ---------- */
T.WORKSPACES = {
  DEV:    { label: 'DEV',    L1: 'shelf', L2: 'keys',  C: 'portal', R1: 'palette', R2: 'deck',  R3: 'trackpad' },
  MAKE:   { label: 'MAKE',   L1: 'ink',   L2: 'ruler', C: 'portal', R1: 'palette', R2: 'dials', R3: 'trackpad' },
  STUDIO: { label: 'STUDIO', L1: 'deck',  L2: 'shelf', C: 'mixer',  R1: 'palette', R2: 'dials', R3: 'trackpad' },
  PAPER:  { label: 'PAPER',  L1: 'ink',   L2: 'shelf', C: 'scan',   R1: 'palette', R2: 'deck',  R3: 'trackpad' },
  OPS:    { label: 'OPS',    L1: 'timer', L2: 'shelf', C: 'winmap', R1: 'sysmon',  R2: 'deck',  R3: 'trackpad' },
};
/* slot rectangles as fractions of the desk (right-handed). B = in front, under the keyboard mask */
T.SLOTS = {
  L1: [0.012, 0.080, 0.178, 0.440], L2: [0.012, 0.535, 0.178, 0.450],
  C:  [0.205, 0.080, 0.530, 0.610],
  R1: [0.750, 0.080, 0.238, 0.340], R2: [0.750, 0.435, 0.238, 0.265], R3: [0.750, 0.715, 0.238, 0.270],
  B:  [0.205, 0.705, 0.530, 0.280],
};

/* ---------- application profiles (context palettes). chords: "mod" = Ctrl (Win/Linux) or ⌘ (macOS) ---------- */
const K = (l, c, g) => ({ l, a: { do: 'key', c }, g });
const TX = (l, s, g) => ({ l, a: { do: 'text', s }, g });
const WS_FILTER = (l, f) => ({ l, g: 'filter', a: { do: 'seq', steps: [{ do: 'key', c: { win: 'ctrl+/', linux: 'ctrl+/', mac: 'cmd+/' } }, { do: 'key', c: 'mod+a' }, { do: 'text', s: f }, { do: 'key', c: 'enter' }] } });
const REDO = { win: 'ctrl+y', mac: 'cmd+shift+z', linux: 'ctrl+shift+z' };

T.PROFILES = [
  { id: 'global', name: 'Desktop', glyph: '◇', ws: 'DEV', match: {},
    buttons: [K('Copy', 'mod+c', 'edit'), K('Paste', 'mod+v', 'edit'), K('Cut', 'mod+x', 'edit'), K('Undo', 'mod+z', 'edit'), K('Redo', REDO, 'edit'), K('Select all', 'mod+a', 'edit'),
      K('Find', 'mod+f', 'nav'), K('Save', 'mod+s', 'file'), K('Close', 'mod+w', 'file'),
      K('Snip', { win: 'win+shift+s', mac: 'cmd+shift+4', linux: 'print' }, 'sys'), K('Switch app', { win: 'alt+tab', mac: 'cmd+tab', linux: 'alt+tab' }, 'sys'),
      K('Overview', { win: 'win+tab', mac: 'ctrl+up', linux: 'super' }, 'sys'), K('Desktop', { win: 'win+d', mac: 'cmd+f3', linux: 'super+d' }, 'sys'),
      K('Snap ◧', { win: 'win+left', linux: 'super+left' }, 'win'), K('Snap ◨', { win: 'win+right', linux: 'super+right' }, 'win'), K('Maximise', { win: 'win+up', linux: 'super+up' }, 'win'),
      K('Clip history', { win: 'win+v' }, 'sys'), K('Emoji', { win: 'win+.', mac: 'ctrl+cmd+space' }, 'sys'), K('Lock', { win: 'win+l', mac: 'ctrl+cmd+q', linux: 'super+l' }, 'sys')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }],
    jog: { l: 'Arrows', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'vscode', name: 'VS Code', glyph: '{}', ws: 'DEV', match: { exe: ['code.exe', 'code', 'code - insiders.exe', 'code-insiders', 'cursor.exe', 'cursor', 'codium', 'vscodium.exe'], title: 'visual studio code|vscodium|cursor' },
    buttons: [K('Command palette', 'mod+shift+p', 'nav'), K('Quick open', 'mod+p', 'nav'), K('Terminal', 'ctrl+`', 'view'), K('New terminal', 'ctrl+shift+`', 'view'), K('Sidebar', 'mod+b', 'view'), K('Explorer', 'mod+shift+e', 'view'),
      K('Search files', 'mod+shift+f', 'nav'), K('Source control', 'ctrl+shift+g', 'view'), K('Format', { win: 'shift+alt+f', mac: 'shift+alt+f', linux: 'ctrl+shift+i' }, 'edit'), K('Comment', 'mod+/', 'edit'),
      K('Go to def', 'f12', 'nav'), K('Peek def', { win: 'alt+f12', mac: 'alt+f12', linux: 'ctrl+shift+f10' }, 'nav'), K('Rename', 'f2', 'edit'), K('Quick fix', 'mod+.', 'edit'),
      K('Run / Debug', 'f5', 'debug'), K('Step over', 'f10', 'debug'), K('Step into', 'f11', 'debug'), K('Step out', 'shift+f11', 'debug'), K('Stop', 'shift+f5', 'debug'), K('Breakpoint', 'f9', 'debug'),
      K('Split editor', 'mod+\\', 'view'), K('Next editor', { win: 'ctrl+pagedown', mac: 'alt+cmd+right', linux: 'ctrl+pagedown' }, 'nav'), K('Prev editor', { win: 'ctrl+pageup', mac: 'alt+cmd+left', linux: 'ctrl+pageup' }, 'nav'),
      K('Back', { win: 'alt+left', mac: 'ctrl+-', linux: 'ctrl+alt+-' }, 'nav'), K('Build task', 'mod+shift+b', 'debug'), K('Zen mode', ['mod+k', 'z'], 'view'), K('MD preview', 'mod+shift+v', 'view'), K('Save all', { win: ['ctrl+k', 's'], mac: 'alt+cmd+s', linux: ['ctrl+k', 's'] }, 'file')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Font zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }, { l: 'Editors', cw: { do: 'key', c: { win: 'ctrl+pagedown', mac: 'alt+cmd+right', linux: 'ctrl+pagedown' } }, ccw: { do: 'key', c: { win: 'ctrl+pageup', mac: 'alt+cmd+left', linux: 'ctrl+pageup' } } }],
    jog: { l: 'Lines', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } } },

  { id: 'browser', name: 'Browser', glyph: '◎', ws: 'DEV', match: { exe: ['chrome.exe', 'chrome', 'google-chrome', 'chromium', 'msedge.exe', 'microsoft-edge', 'firefox.exe', 'firefox', 'brave.exe', 'brave', 'vivaldi.exe', 'opera.exe', 'safari', 'arc.exe'], title: 'google chrome|chromium|edge|firefox|brave|safari' },
    buttons: [K('New tab', 'mod+t', 'tab'), K('Close tab', 'mod+w', 'tab'), K('Reopen tab', 'mod+shift+t', 'tab'), K('Next tab', 'ctrl+tab', 'tab'), K('Prev tab', 'ctrl+shift+tab', 'tab'),
      K('Back', { win: 'alt+left', mac: 'cmd+[', linux: 'alt+left' }, 'nav'), K('Forward', { win: 'alt+right', mac: 'cmd+]', linux: 'alt+right' }, 'nav'), K('Reload', 'mod+r', 'nav'), K('Address bar', 'mod+l', 'nav'), K('Find', 'mod+f', 'nav'),
      K('Zoom +', 'mod+=', 'view'), K('Zoom −', 'mod+-', 'view'), K('Zoom 100%', 'mod+0', 'view'), K('DevTools', { win: 'ctrl+shift+i', mac: 'alt+cmd+i', linux: 'ctrl+shift+i' }, 'dev'),
      K('History', { win: 'ctrl+h', mac: 'cmd+y', linux: 'ctrl+h' }, 'nav'), K('Bookmark', 'mod+d', 'nav'), K('Private window', 'mod+shift+n', 'tab'), K('Fullscreen', { win: 'f11', mac: 'ctrl+cmd+f', linux: 'f11' }, 'view')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }, { l: 'Tabs', cw: { do: 'key', c: 'ctrl+tab' }, ccw: { do: 'key', c: 'ctrl+shift+tab' } }],
    jog: { l: 'Page', cw: { do: 'key', c: 'pagedown' }, ccw: { do: 'key', c: 'pageup' } } },

  { id: 'terminal', name: 'Terminal', glyph: '>_', ws: 'DEV', match: { exe: ['windowsterminal.exe', 'wt.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe', 'gnome-terminal-server', 'konsole', 'alacritty', 'kitty', 'wezterm-gui', 'wezterm-gui.exe', 'iterm2', 'terminal', 'ghostty', 'xterm', 'tilix', 'foot'], title: 'terminal|powershell|bash|zsh' },
    buttons: [K('Interrupt ^C', 'ctrl+c', 'ctl'), K('Clear', 'ctrl+l', 'ctl'), K('History ^R', 'ctrl+r', 'ctl'), K('Prev cmd', 'up', 'ctl'), K('Complete', 'tab', 'ctl'), K('EOF ^D', 'ctrl+d', 'ctl'),
      K('Copy', { win: 'ctrl+shift+c', mac: 'cmd+c', linux: 'ctrl+shift+c' }, 'edit'), K('Paste', { win: 'ctrl+shift+v', mac: 'cmd+v', linux: 'ctrl+shift+v' }, 'edit'), K('New tab', { win: 'ctrl+shift+t', mac: 'cmd+t', linux: 'ctrl+shift+t' }, 'edit'),
      TX('git status', 'git status\n', 'git'), TX('git log', 'git log --oneline -15\n', 'git'), TX('git diff', 'git diff --stat\n', 'git'), TX('ls -la', 'ls -la\n', 'sh'), TX('nvidia-smi', 'nvidia-smi\n', 'gpu'), TX('ollama ps', 'ollama ps\n', 'gpu'), TX('docker ps', 'docker ps\n', 'sh')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'History', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }],
    jog: { l: 'Cursor', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'blender', name: 'Blender', glyph: '◐', ws: 'MAKE', match: { exe: ['blender.exe', 'blender'], title: 'blender' },
    buttons: [K('Front 1', 'numpad1', 'view'), K('Right 3', 'numpad3', 'view'), K('Top 7', 'numpad7', 'view'), K('Back', 'ctrl+numpad1', 'view'), K('Camera 0', 'numpad0', 'view'), K('Persp/Ortho', 'numpad5', 'view'),
      K('Frame sel', 'numpad_dec', 'view'), K('Frame all', 'home', 'view'), K('Grab G', 'g', 'xf'), K('Rotate R', 'r', 'xf'), K('Scale S', 's', 'xf'), K('Edit ⇄', 'tab', 'mode'),
      K('Add ⇧A', 'shift+a', 'obj'), K('Duplicate', 'shift+d', 'obj'), K('Delete', 'delete', 'obj'), K('Shading Z', 'z', 'view'), K('X-ray', 'alt+z', 'view'), K('Sidebar N', 'n', 'view'),
      K('Play', 'space', 'anim'), K('To start', 'shift+left', 'anim'), K('Render F12', 'f12', 'render'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+shift+z', 'edit'), K('Save', 'mod+s', 'file')],
    dials: [{ l: 'Orbit', cw: { do: 'key', c: 'numpad6' }, ccw: { do: 'key', c: 'numpad4' } }, { l: 'Tilt', cw: { do: 'key', c: 'numpad8' }, ccw: { do: 'key', c: 'numpad2' } }, { l: 'Zoom', cw: { do: 'key', c: 'numpad_add' }, ccw: { do: 'key', c: 'numpad_sub' } }],
    jog: { l: 'Frames', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'photoshop', name: 'Photoshop', glyph: 'Ps', ws: 'MAKE', match: { exe: ['photoshop.exe', 'adobe photoshop'], title: 'photoshop' },
    buttons: [K('Brush B', 'b', 'tool'), K('Eraser E', 'e', 'tool'), K('Move V', 'v', 'tool'), K('Marquee M', 'm', 'tool'), K('Lasso L', 'l', 'tool'), K('Q-select W', 'w', 'tool'), K('Eyedrop I', 'i', 'tool'), K('Hand H', 'h', 'tool'),
      K('Swap X', 'x', 'color'), K('Default D', 'd', 'color'), K('Transform', 'mod+t', 'edit'), K('Dup layer', 'mod+j', 'layer'), K('New layer', 'mod+shift+n', 'layer'), K('Deselect', 'mod+d', 'edit'),
      K('Fit', 'mod+0', 'view'), K('100%', 'mod+1', 'view'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+shift+z', 'edit'), K('Save', 'mod+s', 'file'), K('Export as', 'mod+shift+alt+w', 'file')],
    dials: [{ l: 'Brush size', cw: { do: 'key', c: ']' }, ccw: { do: 'key', c: '[' } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }, { l: 'History', cw: { do: 'key', c: 'mod+shift+z' }, ccw: { do: 'key', c: 'mod+z' } }],
    jog: { l: 'Hardness', cw: { do: 'key', c: 'shift+]' }, ccw: { do: 'key', c: 'shift+[' } } },

  { id: 'krita', name: 'Krita', glyph: 'Kr', ws: 'MAKE', match: { exe: ['krita.exe', 'krita'], title: 'krita' },
    buttons: [K('Brush B', 'b', 'tool'), K('Eraser E', 'e', 'tool'), K('Move T', 't', 'tool'), K('Transform', 'mod+t', 'edit'), K('Rotate ⟲ 4', '4', 'view'), K('Rotate ⟳ 6', '6', 'view'), K('Reset rot 5', '5', 'view'), K('Mirror M', 'm', 'view'),
      K('New layer', 'insert', 'layer'), K('Deselect', 'mod+shift+a', 'edit'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+shift+z', 'edit'), K('Save', 'mod+s', 'file')],
    dials: [{ l: 'Brush size', cw: { do: 'key', c: ']' }, ccw: { do: 'key', c: '[' } }, { l: 'Canvas rot', cw: { do: 'key', c: '6' }, ccw: { do: 'key', c: '4' } }, { l: 'History', cw: { do: 'key', c: 'mod+shift+z' }, ccw: { do: 'key', c: 'mod+z' } }],
    jog: { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } } },

  { id: 'gimp', name: 'GIMP', glyph: 'Gi', ws: 'MAKE', match: { exe: ['gimp.exe', 'gimp', 'gimp-2.10', 'gimp-3.0'], title: 'gimp' },
    buttons: [K('Paint P', 'p', 'tool'), K('Eraser ⇧E', 'shift+e', 'tool'), K('Move M', 'm', 'tool'), K('Rect sel R', 'r', 'tool'), K('Free sel F', 'f', 'tool'), K('Fuzzy U', 'u', 'tool'), K('Picker O', 'o', 'tool'),
      K('Select none', 'mod+shift+a', 'edit'), K('Fit', 'mod+shift+j', 'view'), K('100%', '1', 'view'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+y', 'edit')],
    dials: [{ l: 'Brush size', cw: { do: 'key', c: ']' }, ccw: { do: 'key', c: '[' } }, { l: 'Zoom', cw: { do: 'wheel', dy: -1, mods: 'ctrl' }, ccw: { do: 'wheel', dy: 1, mods: 'ctrl' } }, { l: 'History', cw: { do: 'key', c: 'mod+y' }, ccw: { do: 'key', c: 'mod+z' } }],
    jog: { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } } },

  { id: 'figma', name: 'Figma', glyph: 'Fg', ws: 'MAKE', match: { exe: ['figma.exe', 'figma'], title: 'figma' },
    buttons: [K('Move V', 'v', 'tool'), K('Frame F', 'f', 'tool'), K('Rect R', 'r', 'tool'), K('Ellipse O', 'o', 'tool'), K('Line L', 'l', 'tool'), K('Text T', 't', 'tool'), K('Pen P', 'p', 'tool'), K('Comment C', 'c', 'tool'),
      K('Zoom fit', 'shift+1', 'view'), K('Zoom sel', 'shift+2', 'view'), K('Group', 'mod+g', 'obj'), K('Ungroup', 'mod+shift+g', 'obj'), K('Component', 'mod+alt+k', 'obj'), K('Duplicate', 'mod+d', 'obj'), K('Auto layout', 'shift+a', 'obj'), K('Actions', 'mod+/', 'nav'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+shift+z', 'edit')],
    dials: [{ l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'History', cw: { do: 'key', c: 'mod+shift+z' }, ccw: { do: 'key', c: 'mod+z' } }],
    jog: { l: 'Nudge', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'obs', name: 'OBS Studio', glyph: '●', ws: 'STUDIO', match: { exe: ['obs64.exe', 'obs', 'obs-studio'], title: 'obs \\d|obs studio' }, dynamic: 'obs-scenes',
    buttons: [{ l: 'Stream ⏺/⏹', g: 'live', a: { do: 'obs', req: 'ToggleStream' } }, { l: 'Record ⏺/⏹', g: 'live', a: { do: 'obs', req: 'ToggleRecord' } }, { l: 'Pause rec', g: 'live', a: { do: 'obs', req: 'ToggleRecordPause' } },
      { l: 'Virtual cam', g: 'live', a: { do: 'obs', req: 'ToggleVirtualCam' } }, { l: 'Save replay', g: 'live', a: { do: 'obs', req: 'SaveReplayBuffer' } }, { l: 'Studio mode', g: 'view', a: { do: 'obs', req: 'ToggleStudioMode' } },
      { l: 'Mute mic', g: 'audio', a: { do: 'obs', req: 'ToggleInputMute', data: { inputName: 'Mic/Aux' } } }, { l: 'Mute desktop', g: 'audio', a: { do: 'obs', req: 'ToggleInputMute', data: { inputName: 'Desktop Audio' } } }],
    dials: [{ l: 'Mic gain', cw: { do: 'obs', req: 'NudgeInputVolume', data: { inputName: 'Mic/Aux', db: 1 } }, ccw: { do: 'obs', req: 'NudgeInputVolume', data: { inputName: 'Mic/Aux', db: -1 } } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }],
    jog: { l: 'Scenes', cw: { do: 'obs', req: 'NextScene' }, ccw: { do: 'obs', req: 'PrevScene' } } },

  { id: 'resolve', name: 'DaVinci Resolve', glyph: 'Dv', ws: 'STUDIO', match: { exe: ['resolve.exe', 'resolve'], title: 'davinci resolve' },
    buttons: [K('Play', 'space', 'tp'), K('◀◀ J', 'j', 'tp'), K('■ K', 'k', 'tp'), K('▶▶ L', 'l', 'tp'), K('In I', 'i', 'mark'), K('Out O', 'o', 'mark'), K('Marker M', 'm', 'mark'),
      K('Select A', 'a', 'tool'), K('Blade B', 'b', 'tool'), K('Split ⌃B', 'mod+b', 'edit'), K('Ripple del', 'shift+backspace', 'edit'), K('Prev edit', 'up', 'nav'), K('Next edit', 'down', 'nav'), K('Zoom fit', 'shift+z', 'view'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+shift+z', 'edit')],
    dials: [{ l: 'Timeline zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }, { l: 'Edits', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }],
    jog: { l: 'Frames', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'premiere', name: 'Premiere Pro', glyph: 'Pr', ws: 'STUDIO', match: { exe: ['adobe premiere pro.exe', 'adobe premiere pro'], title: 'premiere pro' },
    buttons: [K('Play', 'space', 'tp'), K('◀◀ J', 'j', 'tp'), K('■ K', 'k', 'tp'), K('▶▶ L', 'l', 'tp'), K('In I', 'i', 'mark'), K('Out O', 'o', 'mark'), K('Marker M', 'm', 'mark'),
      K('Select V', 'v', 'tool'), K('Razor C', 'c', 'tool'), K('Add edit', 'mod+k', 'edit'), K('Ripple ◀ Q', 'q', 'edit'), K('Ripple ▶ W', 'w', 'edit'), K('Ripple del', 'shift+delete', 'edit'), K('Zoom seq \\', '\\', 'view'), K('Export', 'mod+m', 'file'), K('Undo', 'mod+z', 'edit')],
    dials: [{ l: 'Zoom', cw: { do: 'key', c: '=' }, ccw: { do: 'key', c: '-' } }, { l: 'Edits', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }],
    jog: { l: 'Frames', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'ableton', name: 'Ableton Live', glyph: '▥', ws: 'STUDIO', match: { exe: ['ableton live 12 suite.exe', 'ableton live 11 suite.exe', 'ableton live 12 standard.exe', 'live'], title: 'ableton live' },
    buttons: [K('Play/Stop', 'space', 'tp'), K('Session ⇄ Arr.', 'tab', 'view'), K('Arr. record', 'f9', 'tp'), K('Audio track', 'mod+t', 'track'), K('MIDI track', 'mod+shift+t', 'track'), K('Group', 'mod+g', 'track'),
      K('Split', 'mod+e', 'edit'), K('Duplicate', 'mod+d', 'edit'), K('Consolidate', 'mod+j', 'edit'), K('Loop sel.', 'mod+l', 'edit'), K('Draw mode B', 'b', 'edit'), K('Browser', { win: 'ctrl+alt+b', mac: 'alt+cmd+b', linux: 'ctrl+alt+b' }, 'view'),
      K('Undo', 'mod+z', 'edit'), K('Redo', REDO, 'edit')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Zoom', cw: { do: 'key', c: '=' }, ccw: { do: 'key', c: '-' } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }],
    jog: { l: 'Nudge', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'wireshark', name: 'Wireshark', glyph: '≋', ws: 'OPS', match: { exe: ['wireshark.exe', 'wireshark'], title: 'wireshark' },
    buttons: [K('Start/Stop cap.', 'mod+e', 'cap'), K('Restart cap.', 'mod+r', 'cap'), K('Capture opts', 'mod+k', 'cap'), K('Find packet', 'mod+f', 'nav'), K('Go to packet', 'mod+g', 'nav'), K('Mark', 'mod+m', 'nav'), K('Time ref', 'mod+t', 'nav'),
      K('Follow TCP', 'ctrl+alt+shift+t', 'follow'), K('Follow UDP', 'ctrl+alt+shift+u', 'follow'), K('Follow TLS', 'ctrl+alt+shift+s', 'follow'), K('Follow HTTP', 'ctrl+alt+shift+h', 'follow'),
      WS_FILTER('SIP', 'sip'), WS_FILTER('Diameter', 'diameter'), WS_FILTER('GTPv2-C', 'gtpv2'), WS_FILTER('PFCP', 'pfcp'), WS_FILTER('NGAP', 'ngap'), WS_FILTER('NAS-5GS', 'nas-5gs'), WS_FILTER('S1AP', 's1ap'), WS_FILTER('SCTP', 'sctp'), WS_FILTER('HTTP/2 SBI', 'http2'), WS_FILTER('RTP', 'rtp'), WS_FILTER('Clear filter', '')],
    dials: [{ l: 'Packets', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }],
    jog: { l: 'Page', cw: { do: 'key', c: 'pagedown' }, ccw: { do: 'key', c: 'pageup' } } },

  { id: 'word', name: 'Word', glyph: 'W', ws: 'PAPER', match: { exe: ['winword.exe', 'microsoft word'], title: '- word$|microsoft word' },
    buttons: [K('Bold', 'mod+b', 'fmt'), K('Italic', 'mod+i', 'fmt'), K('Underline', 'mod+u', 'fmt'), K('Heading 1', 'mod+alt+1', 'style'), K('Heading 2', 'mod+alt+2', 'style'), K('Heading 3', 'mod+alt+3', 'style'), K('Normal', 'mod+shift+n', 'style'),
      K('Bullets', { win: 'ctrl+shift+l', mac: 'cmd+shift+l' }, 'fmt'), K('Center', 'mod+e', 'fmt'), K('Left', 'mod+l', 'fmt'), K('Link', 'mod+k', 'ins'), K('Page break', 'mod+enter', 'ins'), K('Comment', { win: 'ctrl+alt+m', mac: 'cmd+alt+a' }, 'rev'), K('Track changes', 'mod+shift+e', 'rev'), K('Spelling', 'f7', 'rev')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Zoom', cw: { do: 'wheel', dy: -1, mods: 'ctrl' }, ccw: { do: 'wheel', dy: 1, mods: 'ctrl' } }, { l: 'Paragraphs', cw: { do: 'key', c: 'mod+down' }, ccw: { do: 'key', c: 'mod+up' } }],
    jog: { l: 'Page', cw: { do: 'key', c: 'pagedown' }, ccw: { do: 'key', c: 'pageup' } } },

  { id: 'excel', name: 'Excel', glyph: 'X', ws: 'PAPER', match: { exe: ['excel.exe', 'microsoft excel'], title: '- excel$|microsoft excel' },
    buttons: [K('AutoSum', { win: 'alt+=', mac: 'cmd+shift+t' }, 'fx'), K('Filter', { win: 'ctrl+shift+l', mac: 'cmd+shift+f' }, 'data'), K('Table', 'mod+t', 'data'), K('Format cells', 'mod+1', 'fmt'), K('Edit cell', { win: 'f2', mac: 'ctrl+u' }, 'fx'),
      K('Abs ref $', { win: 'f4', mac: 'cmd+t' }, 'fx'), K('Fill down', 'mod+d', 'data'), K('Fill right', 'mod+r', 'data'), K('Today', 'ctrl+;', 'fx'), K('Select col', 'ctrl+space', 'sel'), K('Select row', 'shift+space', 'sel'),
      K('Insert', { win: 'ctrl+shift+=', mac: 'cmd+shift+=' }, 'data'), K('Delete', 'mod+-', 'data'), K('Next sheet', 'ctrl+pagedown', 'nav'), K('Prev sheet', 'ctrl+pageup', 'nav')],
    dials: [{ l: 'Rows', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Cols', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } }, { l: 'Sheets', cw: { do: 'key', c: 'ctrl+pagedown' }, ccw: { do: 'key', c: 'ctrl+pageup' } }],
    jog: { l: 'Page', cw: { do: 'key', c: 'pagedown' }, ccw: { do: 'key', c: 'pageup' } } },

  { id: 'powerpoint', name: 'PowerPoint', glyph: 'P', ws: 'PAPER', match: { exe: ['powerpnt.exe', 'microsoft powerpoint'], title: 'powerpoint' },
    buttons: [K('Start show', { win: 'f5', mac: 'cmd+shift+enter' }, 'show'), K('From here', { win: 'shift+f5', mac: 'cmd+enter' }, 'show'), K('Next ▶', 'right', 'show'), K('◀ Prev', 'left', 'show'), K('Black B', 'b', 'show'), K('White W', 'w', 'show'), K('Laser', 'mod+l', 'show'), K('End', 'esc', 'show'),
      K('New slide', 'mod+m', 'edit'), K('Duplicate', 'mod+d', 'edit'), K('Undo', 'mod+z', 'edit')],
    dials: [{ l: 'Slides', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } }, { l: 'Zoom', cw: { do: 'wheel', dy: -1, mods: 'ctrl' }, ccw: { do: 'wheel', dy: 1, mods: 'ctrl' } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }],
    jog: { l: 'Slides', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'media', name: 'Music / Video', glyph: '♪', ws: 'STUDIO', match: { exe: ['spotify.exe', 'spotify', 'vlc.exe', 'vlc', 'music', 'mpv'], title: 'spotify|vlc' },
    buttons: [{ l: 'Play/Pause', g: 'tp', a: { do: 'media', op: 'playpause' } }, { l: 'Next', g: 'tp', a: { do: 'media', op: 'next' } }, { l: 'Previous', g: 'tp', a: { do: 'media', op: 'prev' } },
      { l: 'Vol +', g: 'vol', a: { do: 'media', op: 'volup' } }, { l: 'Vol −', g: 'vol', a: { do: 'media', op: 'voldown' } }, { l: 'Mute', g: 'vol', a: { do: 'media', op: 'mute' } }, K('Shuffle', 'mod+s', 'tp'), K('Repeat', 'mod+r', 'tp')],
    dials: [{ l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }, { l: 'Seek', cw: { do: 'key', c: 'shift+right' }, ccw: { do: 'key', c: 'shift+left' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }],
    jog: { l: 'Tracks', cw: { do: 'media', op: 'next' }, ccw: { do: 'media', op: 'prev' } } },

  { id: 'files', name: 'Files', glyph: '▤', ws: 'PAPER', match: { exe: ['explorer.exe', 'finder', 'nautilus', 'dolphin', 'thunar', 'nemo'], title: 'file explorer|finder' },
    buttons: [K('New folder', 'mod+shift+n', 'file'), K('Rename', { win: 'f2', mac: 'enter', linux: 'f2' }, 'file'), K('Up', { win: 'alt+up', mac: 'cmd+up', linux: 'alt+up' }, 'nav'), K('Back', { win: 'alt+left', mac: 'cmd+[', linux: 'alt+left' }, 'nav'),
      K('Properties', { win: 'alt+enter', mac: 'cmd+i', linux: 'alt+enter' }, 'file'), K('Address', { win: 'ctrl+l', mac: 'cmd+shift+g', linux: 'ctrl+l' }, 'nav'), K('Hidden files', { mac: 'cmd+shift+.', linux: 'ctrl+h' }, 'view'), K('Quick look', { mac: 'space' }, 'view'), K('New window', 'mod+n', 'nav'), K('Search', 'mod+f', 'nav')],
    dials: [{ l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Select', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } }, { l: 'Icon size', cw: { do: 'wheel', dy: -1, mods: 'ctrl' }, ccw: { do: 'wheel', dy: 1, mods: 'ctrl' } }],
    jog: { l: 'Select', cw: { do: 'key', c: 'down' }, ccw: { do: 'key', c: 'up' } } },

  { id: 'calls', name: 'Calls', glyph: '☏', ws: 'OPS', match: { exe: ['zoom.exe', 'zoom.us', 'zoom', 'ms-teams.exe', 'teams', 'discord.exe', 'discord', 'slack.exe', 'slack'], title: 'zoom meeting|microsoft teams|discord|slack' },
    buttons: [K('Zoom mute', { win: 'alt+a', mac: 'cmd+shift+a', linux: 'alt+a' }, 'zoom'), K('Zoom video', { win: 'alt+v', mac: 'cmd+shift+v', linux: 'alt+v' }, 'zoom'), K('Zoom share', { win: 'alt+s', mac: 'cmd+shift+s', linux: 'alt+s' }, 'zoom'), K('Zoom hand', 'alt+y', 'zoom'),
      K('Teams mute', 'mod+shift+m', 'teams'), K('Teams cam', 'mod+shift+o', 'teams'), K('Teams hand', 'mod+shift+k', 'teams'),
      K('Discord mute', 'mod+shift+m', 'discord'), K('Discord deafen', 'mod+shift+d', 'discord'), K('Slack switcher', 'mod+k', 'slack'), K('Slack huddle', 'mod+shift+h', 'slack')],
    dials: [{ l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'Zoom', cw: { do: 'key', c: 'mod+=' }, ccw: { do: 'key', c: 'mod+-' } }],
    jog: { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } } },

  { id: 'kicad', name: 'KiCad', glyph: '⊞', ws: 'MAKE', match: { exe: ['kicad.exe', 'kicad', 'pcbnew', 'pcbnew.exe', 'eeschema', 'eeschema.exe'], title: 'kicad|pcb editor|schematic editor' },
    buttons: [K('Move M', 'm', 'edit'), K('Rotate R', 'r', 'edit'), K('Properties E', 'e', 'edit'), K('Route X', 'x', 'route'), K('Via V', 'v', 'route'), K('Refill B', 'b', 'route'), K('Zoom fit', 'home', 'view'), K('Zoom in F1', 'f1', 'view'), K('Zoom out F2', 'f2', 'view'), K('3D view', 'alt+3', 'view'), K('Delete', 'delete', 'edit'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+y', 'edit')],
    dials: [{ l: 'Zoom', cw: { do: 'key', c: 'f1' }, ccw: { do: 'key', c: 'f2' } }, { l: 'Scroll', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'History', cw: { do: 'key', c: 'mod+y' }, ccw: { do: 'key', c: 'mod+z' } }],
    jog: { l: 'Nudge', cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } },

  { id: 'freecad', name: 'FreeCAD', glyph: '⬡', ws: 'MAKE', match: { exe: ['freecad.exe', 'freecad'], title: 'freecad' },
    buttons: [K('Iso 0', '0', 'view'), K('Front 1', '1', 'view'), K('Top 2', '2', 'view'), K('Right 3', '3', 'view'), K('Rear 4', '4', 'view'), K('Bottom 5', '5', 'view'), K('Left 6', '6', 'view'), K('Fit all', ['v', 'f'], 'view'), K('Fit sel.', ['v', 's'], 'view'), K('Undo', 'mod+z', 'edit'), K('Redo', 'mod+y', 'edit'), K('Save', 'mod+s', 'file')],
    dials: [{ l: 'Zoom', cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } }, { l: 'History', cw: { do: 'key', c: 'mod+y' }, ccw: { do: 'key', c: 'mod+z' } }, { l: 'Volume', cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } }],
    jog: { l: 'Views', cw: { do: 'key', c: '3' }, ccw: { do: 'key', c: '1' } } },
];

/* ---------- deck macros (global, user-editable) ---------- */
T.DEFAULT_MACROS = [
  { id: 'focus25', l: 'Focus 25', g: 'flow', steps: [{ do: 'timer', min: 25 }, { do: 'ws', name: 'DEV' }] },
  { id: 'snip', l: 'Screen snip', g: 'sys', steps: [{ do: 'key', c: { win: 'win+shift+s', mac: 'cmd+shift+4', linux: 'print' } }] },
  { id: 'gitst', l: 'git status', g: 'git', steps: [{ do: 'text', s: 'git status\n' }] },
  { id: 'gitci', l: 'git commit …', g: 'git', steps: [{ do: 'text', s: 'git commit -am ""' }, { do: 'key', c: 'left' }] },
  { id: 'pytest', l: 'pytest -q', g: 'dev', steps: [{ do: 'text', s: 'pytest -q\n' }] },
  { id: 'ollamaps', l: 'Ollama ps', g: 'gpu', steps: [{ do: 'run', id: 'ollama_ps' }] },
  { id: 'nvsmi', l: 'nvidia-smi', g: 'gpu', steps: [{ do: 'run', id: 'nvidia_smi' }] },
  { id: 'paper', l: 'Scan paper', g: 'flow', steps: [{ do: 'ws', name: 'PAPER' }, { do: 'tool', name: 'scan' }] },
  { id: 'code', l: 'Open editor', g: 'app', steps: [{ do: 'launch', id: 'code' }] },
  { id: 'overview', l: 'Overview', g: 'sys', steps: [{ do: 'key', c: { win: 'win+tab', mac: 'ctrl+up', linux: 'super' } }] },
  { id: 'play', l: 'Play / Pause', g: 'media', steps: [{ do: 'media', op: 'playpause' }] },
  { id: 'lock', l: 'Lock screen', g: 'sys', steps: [{ do: 'key', c: { win: 'win+l', mac: 'ctrl+cmd+q', linux: 'super+l' } }] },
];

/* ---------- default runtime configuration ---------- */
T.defaults = () => ({
  v: 3,
  desk: { w: 1000, h: 562.5, handed: 'right', kb: { on: true, x: 0.28, y: 0.72, w: 0.44, h: 0.26 }, minTarget: 16 },
  output: { res: [1920, 1080], corners: [[0.035, 0.05], [0.965, 0.03], [0.985, 0.97], [0.015, 0.95]], mesh: { on: false, nx: 5, ny: 4, d: null }, gain: 1, tint: [1, 1, 1], feather: 0.006, flipX: false, flipY: false, grid: false, dimHands: true, headGuard: true },
  input: { air: 'pinch', dwellMs: 650, euro: { minCutoff: 1.2, beta: 0.02, dCutoff: 1.0 }, bias: { sim: [0, 0], air: [0, 0], host: [0, 0] }, predictMs: 40, simHand: true },
  calib: { H_desk_cam: null, k1: 0, aspect: 16 / 9, rms: null, rmsMm: null, method: null, at: null, step: 16, settleMs: 170, accuracy: null, latencyMs: null, sim: { yaw: 7, pitch: 11, k1: -0.035, noise: 5, ambient: 22 } },
  host: { url: '', mode: 'sim' },          // the host token is never part of the config (sessionStorage only, see T.runToken)
  ui: { ws: 'AUTO', tab: 'desk' },
  scheme: { projector: 'optoma-gt2000hdr', custom: null, mount: 'overhead', d1: 250, ambient: 300, derate: 0.75, sensor: 'femto-bolt-nfov', sensorH: 800, viewDist: 600, viewElev: 50, refl: 0.7, projHz: 60, mains: 50, procMs: 15 },
  tribunal: { strict: true, acks: {} },
  midi: { outId: null, ch: 1, faders: [20, 21, 22, 23], pads: [36, 38, 42, 46, 39, 45, 48, 49] },
  macros: T.deepClone(T.DEFAULT_MACROS),
  tokens: { '10': { l: 'timer puck', tag: 'timer' }, '11': { l: 'scroll puck', dial: { cw: { do: 'wheel', dy: 1 }, ccw: { do: 'wheel', dy: -1 } } }, '12': { l: 'volume puck', dial: { cw: { do: 'media', op: 'volup' }, ccw: { do: 'media', op: 'voldown' } } },
    '13': { l: 'jog puck', dial: { cw: { do: 'key', c: 'right' }, ccw: { do: 'key', c: 'left' } } }, '20': { l: 'DEV', ws: 'DEV' }, '21': { l: 'MAKE', ws: 'MAKE' }, '22': { l: 'STUDIO', ws: 'STUDIO' }, '23': { l: 'PAPER', ws: 'PAPER' }, '24': { l: 'OPS', ws: 'OPS' } },
  userProfiles: [],
});

T.cfg = null;           // live config (leader-authoritative)
T.loadCfg = () => {
  const d = T.defaults();
  const s = T.store.get('cfg', null);
  if (s && s.v === d.v) T.deepMerge(d, s);
  if (d.host) delete d.host.token;          // older builds stored it; localStorage of file:// pages is shared by every local file
  T.cfg = d; return d;
};
T.cfgPublic = () => { const c = T.deepClone(T.cfg); if (c.host) delete c.host.token; return c; };
T.saveCfg = () => T.store.set('cfg', T.cfgPublic());
T.allProfiles = () => (T.cfg && T.cfg.userProfiles && T.cfg.userProfiles.length ? [...T.cfg.userProfiles, ...T.PROFILES] : T.PROFILES);
T.matchProfile = (focus) => {
  if (!focus) return T.PROFILES[0];
  const exe = String(focus.exe || focus.app || '').toLowerCase(), title = String(focus.title || '').toLowerCase();
  for (const p of T.allProfiles()) {
    if (!p.match || (!p.match.exe && !p.match.title)) continue;
    if (p.match.exe && p.match.exe.some((e) => exe === e || exe.endsWith('/' + e) || exe.endsWith('\\' + e))) return p;
  }
  for (const p of T.allProfiles()) {
    if (p.match && p.match.title) { try { if (new RegExp(p.match.title, 'i').test(title)) return p; } catch (e) { /* bad user regex */ } }
  }
  return T.PROFILES[0];
};
