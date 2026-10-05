

# ==================================================================================================
# sensing: depth sources → touch engine; IR light plane; ArUco tangibles; TUIO in; tap calibration
# ==================================================================================================
class DepthSource:
    """Yields (depth_mm float32 HxW with 0 = invalid, timestamp). Subclasses wrap vendor SDKs."""
    name = "base"
    desk_aligned = False            # True when the image already spans the desk (synthetic)

    def open(self): ...
    def read(self): raise NotImplementedError
    def close(self): ...


class SyntheticDepth(DepthSource):
    """A desk at 800 mm with sensor noise, a mug, a phone, and 1–2 arms whose index fingers tap on a schedule.
    `truth` exposes the true fingertip (u, v, z_mm) so the engine can be tested end-to-end."""
    name = "synthetic"
    desk_aligned = True

    def __init__(self, w=320, h=180, desk_mm=(1000.0, 562.5), hz=30, seed=3, arms=2):
        self.w, self.h, self.desk, self.hz, self.arms = w, h, desk_mm, hz, arms
        self.rng = np.random.default_rng(seed)
        self.t0 = time.time()
        self.frame_i = 0
        self.truth = []
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.X = (xx + 0.5) / w * desk_mm[0]
        self.Y = (yy + 0.5) / h * desk_mm[1]
        self.base = 800.0 + (self.X - desk_mm[0] / 2) * 0.004 - (self.Y - desk_mm[1] / 2) * 0.003     # slightly tilted desk

    def finger_state(self, t, k):
        """deterministic choreography: finger k glides along a path and taps every ~1.6 s"""
        W, H = self.desk
        cx = W * (0.3 + 0.4 * k) + W * 0.12 * math.sin(0.7 * t + k)
        cy = H * 0.45 + H * 0.15 * math.cos(0.9 * t + 2 * k)
        ph = ((t + 0.8 * k) % 1.6) / 1.6
        z = 6.0 if 0.35 < ph < 0.65 else 45.0                        # touching for ~0.48 s per cycle
        return cx, cy, z

    def read(self):
        t = self.frame_i / self.hz
        self.frame_i += 1
        W, H = self.desk
        hmap = np.zeros_like(self.X)
        self.truth = []
        if self.frame_i <= 30:                                                                  # empty desk first: the engine learns its background
            depth = self.base + self.rng.normal(0, 1.4, hmap.shape).astype(np.float32)
            return depth.astype(np.float32), time.time()
        hmap = np.maximum(hmap, np.where((self.X - W * 0.86) ** 2 + (self.Y - H * 0.25) ** 2 < 40 ** 2, 95.0, 0.0))          # mug
        hmap = np.maximum(hmap, np.where((np.abs(self.X - W * 0.12) < 37) & (np.abs(self.Y - H * 0.3) < 77), 8.0, 0.0))     # phone
        for k in range(self.arms):
            fx, fy, fz = self.finger_state(t, k)
            self.truth.append((fx / W, fy / H, fz))
            ex, ey = fx + (180 if k else -180) * 0.6, H + 60                                  # elbow off the near edge
            vx, vy = fx - ex, fy - ey
            L = math.hypot(vx, vy)
            ux, uy = vx / L, vy / L
            px, py = self.X - ex, self.Y - ey
            a = L - (px * ux + py * uy)                                                         # from the fingertip back toward the elbow
            b = (px * uy - py * ux) * (1.0 if k else -1.0)                                      # across, + toward the thumb (arm 1 is a right arm)
            # a hand pointing with the INDEX finger: the finger leaves the fist at its thumb-side edge (thumb folded under),
            # and the middle, ring and little fingers are curled into three high knuckles that never reach the touch band
            fin = (a >= 0) & (a < 75) & (np.abs(b) < 8.5)                                       # index finger, 75 mm
            taper = np.clip((a - 75) / 100.0, 0, 1)
            hand = (a >= 75) & (a < 175) & (b < 16 + 15 * taper) & (b > -62 + 17 * taper)
            front = 60.0 - 2.5 * np.cos(2 * math.pi * (b + 19.5) / 17.0)                      # three curled knuckles: a shallow scallop,
            curl = (a >= front) & (a < 75) & (b > -62) & (b < -11)                             # too blunt to read as fingertips
            fore = (a >= 175) & (np.abs(b + 7) < 38)
            finger_h = fz + (55.0 - fz) * np.clip(a / 75.0, 0, 1)                              # slopes continuously up into the hand
            hmap = np.where(fin, np.maximum(hmap, finger_h), hmap)
            hmap = np.where(curl, np.maximum(hmap, 50.0), hmap)
            hmap = np.where(hand, np.maximum(hmap, 55.0), hmap)
            hmap = np.where(fore, np.maximum(hmap, 75.0), hmap)
        depth = self.base - hmap + self.rng.normal(0, 1.4, hmap.shape).astype(np.float32)
        depth[self.rng.random(depth.shape) < 0.004] = 0                                         # dropouts
        return depth.astype(np.float32), time.time()


class RealSenseDepth(DepthSource):
    name = "realsense"

    def open(self):
        import pyrealsense2 as rs  # type: ignore
        self.rs = rs
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 60)
        prof = self.pipe.start(cfg)
        self.scale = prof.get_device().first_depth_sensor().get_depth_scale() * 1000.0             # → mm
        self.spatial, self.temporal = rs.spatial_filter(), rs.temporal_filter()

    def read(self):
        f = self.pipe.wait_for_frames(1000).get_depth_frame()
        f = self.temporal.process(self.spatial.process(f))
        return np.asanyarray(f.get_data()).astype(np.float32) * self.scale, time.time()

    def close(self):
        try:
            self.pipe.stop()
        except Exception:
            pass


class OrbbecDepth(DepthSource):
    name = "orbbec"

    def open(self):
        from pyorbbecsdk import Pipeline, Config, OBSensorType  # type: ignore  (pip install pyorbbecsdk2)
        self.pipe, cfg = Pipeline(), Config()
        prof = self.pipe.get_stream_profile_list(OBSensorType.DEPTH_SENSOR).get_default_video_stream_profile()
        cfg.enable_stream(prof)
        self.pipe.start(cfg)

    def read(self):
        while True:
            fs = self.pipe.wait_for_frames(200)
            d = fs.get_depth_frame() if fs else None
            if d is not None:
                arr = np.frombuffer(d.get_data(), dtype=np.uint16).reshape(d.get_height(), d.get_width()).astype(np.float32)
                return arr * float(d.get_depth_scale()), time.time()

    def close(self):
        try:
            self.pipe.stop()
        except Exception:
            pass


class K4ADepth(DepthSource):
    """Azure Kinect, or Orbbec Femto Bolt/Mega through Orbbec's K4A wrapper."""
    name = "k4a"

    def open(self):
        from pyk4a import PyK4A, Config, DepthMode, ColorResolution, FPS  # type: ignore
        self.k = PyK4A(Config(color_resolution=ColorResolution.OFF, depth_mode=DepthMode.NFOV_UNBINNED, camera_fps=FPS.FPS_30))
        self.k.start()

    def read(self):
        return self.k.get_capture().depth.astype(np.float32), time.time()

    def close(self):
        try:
            self.k.stop()
        except Exception:
            pass


class Freenect2Depth(DepthSource):
    name = "freenect2"

    def open(self):
        from pylibfreenect2 import Freenect2, SyncMultiFrameListener, FrameType, CpuPacketPipeline  # type: ignore
        self.fn = Freenect2()
        self.dev = self.fn.openDevice(self.fn.getDeviceSerialNumber(0), pipeline=CpuPacketPipeline())
        self.lst = SyncMultiFrameListener(FrameType.Depth)
        self.dev.setIrAndDepthFrameListener(self.lst)
        self.dev.startStreams(rgb=False, depth=True)

    def read(self):
        fr = self.lst.waitForNewFrame()
        d = fr["depth"].asarray().copy()
        self.lst.release(fr)
        return d.astype(np.float32), time.time()

    def close(self):
        try:
            self.dev.stop(); self.dev.close()
        except Exception:
            pass


class ReplayDepth(DepthSource):
    name = "replay"

    def __init__(self, path):
        self.frames = np.load(path)["depth"]
        self.i = 0

    def read(self):
        f = self.frames[self.i % len(self.frames)]
        self.i += 1
        time.sleep(1 / 30)
        return f.astype(np.float32), time.time()


def make_depth(src: str) -> DepthSource:
    s = src.lower()
    if s == "synthetic":
        return SyntheticDepth()
    if s.startswith("replay:"):
        return ReplayDepth(src.split(":", 1)[1])
    return {"realsense": RealSenseDepth, "orbbec": OrbbecDepth, "k4a": K4ADepth, "femto": K4ADepth, "freenect2": Freenect2Depth, "kinect2": Freenect2Depth}[s]()


# -------------------------------- the touch engine --------------------------------
class Track:
    __slots__ = ("id", "u", "v", "raw", "z", "down", "cnt_on", "cnt_off", "age", "fx", "fy", "seen")

    def __init__(self, tid, euro):
        self.id, self.down, self.cnt_on, self.cnt_off, self.age, self.seen = tid, False, 0, 0, 0, True
        self.u = self.v = self.z = 0.0
        self.raw = (0.0, 0.0)
        self.fx, self.fy = OneEuro(euro["min_cutoff"], euro["beta"], euro["d_cutoff"]), OneEuro(euro["min_cutoff"], euro["beta"], euro["d_cutoff"])


class TouchEngine:
    """Depth → contacts.
    Wilson (ITS 2010): per-pixel background, touch = thin height band above the surface.
    DIRECT (ISS 2016): fingers belong to an arm that enters from the frame edge; the tip is the geodesically farthest
    point from that edge; contact uses hysteresis; a rolling background absorbs things that stay still."""

    def __init__(self, cfg: dict, desk_mm=(1000.0, 562.5), sensor_h_mm=800.0):
        if cv2 is None or np is None:
            raise RuntimeError("the depth touch engine needs numpy + opencv")
        self.c = cfg
        self.desk = desk_mm
        self.sensor_h = sensor_h_mm
        self.bg = None
        self.bg0 = None
        self.sigma = None
        self.learn = []
        self.tracks: dict = {}
        self.next_id = 1
        self.H = None                 # raw px → desk normalised
        self.shape = None
        self.stats = {"frames": 0, "ms": 0.0, "contacts": 0}
        self.still_since = None

    # --- geometry helpers ---
    def band(self):
        h = self.sensor_h
        lo = self.c["band_lo"] if self.c["band_lo"] is not None else max(3.0, 3.0 + (h - 750) * 3 / 750)
        hi = self.c["band_hi"] if self.c["band_hi"] is not None else 14.0 + (h - 750) * 16 / 750
        return lo, hi

    def to_desk(self, x, y):
        if self.H is not None:
            return h_apply(self.H, x, y)
        H, W = self.shape
        return x / W, y / H

    def mm_per_px(self):
        H, W = self.shape
        a = self.to_desk(W / 2, H / 2)
        b = self.to_desk(W / 2 + 1, H / 2)
        c = self.to_desk(W / 2, H / 2 + 1)
        return math.sqrt(abs((b[0] - a[0]) * self.desk[0] * (c[1] - a[1]) * self.desk[1] - (b[1] - a[1]) * self.desk[1] * (c[0] - a[0]) * self.desk[0]))

    def relearn(self):
        self.bg = None
        self.bg0 = None
        self.learn = []

    # --- main step ---
    def step(self, depth_full, t):
        t0 = time.perf_counter()
        k = max(1, int(self.c["downsample"]))
        Hh, Ww = depth_full.shape[0] // k, depth_full.shape[1] // k
        d = depth_full[:Hh * k, :Ww * k].reshape(Hh, k, Ww, k)
        valid = d > 0
        cnt = valid.sum((1, 3))
        ds = np.where(cnt > 0, (d * valid).sum((1, 3)) / np.maximum(cnt, 1), 0).astype(np.float32)
        self.shape = (depth_full.shape[0], depth_full.shape[1])
        if self.bg is None:
            self.learn.append(ds)
            if len(self.learn) >= 24:
                st = np.stack(self.learn)
                st = np.where(st > 0, st, np.nan)
                self.bg = np.nan_to_num(np.nanmedian(st, 0), nan=0.0).astype(np.float32)
                mad = np.nan_to_num(np.nanmedian(np.abs(st - self.bg), 0), nan=5.0)
                self.sigma = np.clip(mad * 1.4826, 0.5, 8.0).astype(np.float32)
                self.bg0 = self.bg.copy()
                self.learn = []
                log.info("depth background learned (median σ %.2f mm)", float(np.median(self.sigma)))
            return None
        lo, hi = self.band()
        hmap = np.where((ds > 0) & (self.bg > 0), self.bg - ds, 0).astype(np.float32)
        thr = np.maximum(lo, 3 * self.sigma)
        above = (hmap > thr).astype(np.uint8)                        # no morphological opening: a 17 mm finger is only ~3 px wide here
        n, lab, stats, cents = cv2.connectedComponentsWithStats(above, connectivity=8)
        mmpp = self.mm_per_px() * k
        tips, hands, heads, objects, palm = [], [], [], [], False
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < self.c["min_blob_px"]:
                continue
            sub = lab[y:y + h, x:x + w] == i
            hs = hmap[y:y + h, x:x + w]
            hmax = float(hs[sub].max())
            border = x == 0 or y == 0 or x + w >= Ww or y + h >= Hh
            if hmax >= self.c["head_mm"]:
                cx, cy = cents[i]
                u, v = self.to_desk((cx + 0.5) * k, (cy + 0.5) * k)
                heads.append({"x": u, "y": v, "r": 0.5 * math.sqrt(area) * mmpp / self.desk[0]})
                continue
            if border and hmax >= self.c["arm_mm"]:
                contact_area = float(((hs <= hi) & sub).sum()) * mmpp * mmpp
                if contact_area > self.c["palm_area_mm2"]:
                    palm = True
                tips += self._tips(sub, hs, x, y, k, mmpp, hi, Ww, Hh)
                cnts, _ = cv2.findContours(sub.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if cnts:
                    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))[:, 0, :]
                    hands.append([list(self.to_desk((px + x + 0.5) * k, (py + y + 0.5) * k)) for px, py in hull[:: max(1, len(hull) // 24)]])
            elif not border:
                u0, v0 = self.to_desk((x + 0.5) * k, (y + 0.5) * k)
                u1, v1 = self.to_desk((x + w + 0.5) * k, (y + h + 0.5) * k)
                objects.append({"kind": "object", "x": (u0 + u1) / 2, "y": (v0 + v1) / 2, "w": abs(u1 - u0), "h": abs(v1 - v0), "hmax": round(hmax, 1)})
        contacts = self._track(tips, t, lo, hi)
        self._roll_bg(ds, hmap, lo, t, bool(tips))
        self.stats = {"frames": self.stats["frames"] + 1, "ms": round((time.perf_counter() - t0) * 1000, 2), "contacts": sum(1 for c in contacts if c["phase"] != "hover"),
                      "band_mm": [round(lo, 1), round(hi, 1)], "sigma_mm": round(float(np.median(self.sigma)), 2)}
        return {"contacts": contacts, "hands": hands, "heads": heads, "objects": objects, "palm": palm}

    def _tips(self, sub, hs, ox, oy, k, mmpp, hi, Ww, Hh):
        """geodesic distance from the arm's entry pixels; tips = local maxima of that distance"""
        h, w = sub.shape
        D = np.full(sub.shape, -1, np.int32)
        seed = np.zeros_like(sub)
        if oy == 0: seed[0, :] = sub[0, :]
        if ox == 0: seed[:, 0] |= sub[:, 0]
        if oy + h >= Hh: seed[-1, :] |= sub[-1, :]
        if ox + w >= Ww: seed[:, -1] |= sub[:, -1]
        # geodesic distance from the entry edge, propagating only between pixels of similar height, so a flood never
        # jumps from an arm onto a phone or book lying under it (height continuity stands in for DIRECT's IR edges)
        jump = self.c.get("jump_mm", 30.0)
        up = np.abs(hs[:-1, :] - hs[1:, :]) < jump
        lf = np.abs(hs[:, :-1] - hs[:, 1:]) < jump
        front = seed.copy()
        D[front] = 0
        dist = 0
        while front.any() and dist < 2000:
            dist += 1
            nxt = np.zeros_like(front)
            nxt[:-1, :] |= front[1:, :] & up
            nxt[1:, :] |= front[:-1, :] & up
            nxt[:, :-1] |= front[:, 1:] & lf
            nxt[:, 1:] |= front[:, :-1] & lf
            nxt &= sub & (D < 0)
            D[nxt] = dist
            front = nxt
        if D.max() <= 0:
            return []
        Df = D.astype(np.float32)
        loc = (D > 0) & (Df >= cv2.dilate(Df, np.ones((5, 5), np.uint8))) & (Df >= 0.55 * Df.max()) & (Df * mmpp >= 60)
        ys, xs = np.nonzero(loc)
        order = np.argsort(-Df[ys, xs])
        sep = self.c["tip_sep_mm"] / mmpp
        tips = []
        r_px = max(1.5, 7.0 / mmpp)
        pad = self.c.get("pad_mm", 5.0) / mmpp                         # fingerpad sits ~5 mm behind the extremal point
        for j in order:
            px, py = xs[j], ys[j]
            if any(math.hypot(px - q[0], py - q[1]) < sep for q in tips):
                continue
            tips.append((px, py))
            if len(tips) >= 5:
                break
        out = []
        for rank, (px, py) in enumerate(tips):
            dtip = D[py, px]
            yy, xx = np.ogrid[:h, :w]
            reg = sub & (D >= dtip - r_px) & ((xx - px) ** 2 + (yy - py) ** 2 <= (2 * r_px) ** 2)
            zs = hs[reg]
            if zs.size == 0:
                continue
            z = float(np.median(zs))
            ry, rx = np.nonzero(reg)
            ax, ay = px - rx.mean(), py - ry.mean()                    # finger direction: region centroid → extremal pixel
            n = math.hypot(ax, ay) or 1.0
            cx, cy = px - ax / n * pad, py - ay / n * pad
            if rank > 0:
                # extra extremities only count when they are fingers: low at the tip AND still low a finger-width inward.
                # The rim of a fist, a knuckle or the edge of a hand is depth-mixed with the desk (ToF/stereo "flying
                # pixels", and our own down-sampling), so its outermost pixels can read touch-low while it rises at once.
                near = sub & ((xx - px) ** 2 + (yy - py) ** 2 <= (2 * r_px) ** 2)                 # a fingertip-sized disc
                z_near = float(np.percentile(hs[near], 75)) if near.any() else z
                if z > hi * 1.5 or z_near > hi * 2.5:
                    continue
            rawx, rawy = (ox + cx + 0.5) * k, (oy + cy + 0.5) * k
            u, v = self.to_desk(rawx, rawy)
            out.append({"u": u, "v": v, "z": z, "raw": (rawx, rawy)})
        return out

    def _track(self, tips, t, lo, hi):
        euro = self.c["euro"]
        W, H = self.desk
        for tr in self.tracks.values():
            tr.seen = False
        maxj = self.c["max_jump_mm"]
        pairs = sorted(((math.hypot((tp["u"] - tr.u) * W, (tp["v"] - tr.v) * H), i, tr.id) for i, tp in enumerate(tips) for tr in self.tracks.values()))
        used_t, used_p = set(), set()
        for dmm, i, tid in pairs:
            if dmm > maxj or i in used_p or tid in used_t:
                continue
            used_p.add(i); used_t.add(tid)
            self._update(self.tracks[tid], tips[i], t)
        for i, tp in enumerate(tips):
            if i not in used_p:
                tr = Track(self.next_id, euro)
                self.next_id += 1
                self.tracks[tr.id] = tr
                self._update(tr, tp, t)
        out = []
        for tid, tr in list(self.tracks.items()):
            if not tr.seen:
                tr.cnt_off += 1
                if tr.down and tr.cnt_off >= self.c["up_frames"]:
                    out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "up"})
                    tr.down = False
                if tr.cnt_off > 4:
                    del self.tracks[tid]
                continue
            touching = tr.z <= (hi if tr.down else hi - 2.0)             # hysteresis: easier to stay down than to go down
            if touching:
                tr.cnt_on += 1
                tr.cnt_off = 0
            else:
                tr.cnt_off += 1
                tr.cnt_on = 0
            if not tr.down and tr.cnt_on >= self.c["down_frames"]:
                tr.down = True
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "down"})
            elif tr.down and tr.cnt_off >= self.c["up_frames"]:
                tr.down = False
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "up"})
            elif tr.down:
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "move"})
            elif tr.z <= self.c["hover_mm"]:
                out.append({"id": tid, "x": tr.u, "y": tr.v, "z": tr.z, "phase": "hover"})
        return out

    def _update(self, tr, tp, t):
        W, H = self.desk
        tr.u = tr.fx(tp["u"] * W, t) / W
        tr.v = tr.fy(tp["v"] * H, t) / H
        tr.z, tr.raw, tr.seen = tp["z"], tp["raw"], True
        tr.age += 1

    def _roll_bg(self, ds, hmap, lo, t, active):
        """slow update where the surface is quiet; absorb objects that stay still for stun_s (not while a hand is present)"""
        quiet = (np.abs(hmap) < lo) & (ds > 0)
        self.bg[quiet] = self.bg[quiet] * 0.98 + ds[quiet] * 0.02
        if active:
            self.still_since = None
            return
        if self.still_since is None:
            self.still_since = t
        elif t - self.still_since > self.c["stun_s"]:
            placed = (hmap > lo) & (hmap < self.c["arm_mm"]) & (ds > 0)
            self.bg[placed] = ds[placed]
            self.still_since = t


class LightPlane:
    """IR light curtain: a Class-1 850 nm line laser 1–2 mm above the desk; an IR-pass camera sees fingertips as bright blobs."""

    def __init__(self, index: int, thresh=200):
        self.cap = cv2.VideoCapture(index)
        self.thresh = thresh
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} not available")

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            return None, None
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, b = cv2.threshold(cv2.GaussianBlur(g, (5, 5), 0), self.thresh, 255, cv2.THRESH_BINARY)
        n, lab, st, cen = cv2.connectedComponentsWithStats(b, connectivity=8)
        pts = [(float(cen[i][0]), float(cen[i][1])) for i in range(1, n) if 12 <= st[i][4] <= 4000]
        return pts, g.shape

    def close(self):
        self.cap.release()


class Tangibles:
    """ArUco MIP 36h12 tokens (same dictionary as js-aruco2 in the page). Markers 0–3 placed on the projected image
    corners calibrate the camera automatically; every other id is reported as a token with position + rotation."""

    def __init__(self, index: int, corner_ids=(0, 1, 2, 3)):
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} not available")
        self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12), cv2.aruco.DetectorParameters())
        self.corner_ids = list(corner_ids)
        self.H = None
        self.last = None
        self.lock = threading.Lock()                           # one reader at a time: sensing thread vs. Gray-code capture

    def grab(self):
        with self.lock:
            ok, frame = self.cap.read()
        return frame if ok else None

    def read(self):
        frame = self.grab()
        if frame is None:
            return None
        self.last = frame
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.det.detectMarkers(g)
        found = {}
        if ids is not None:
            for c, i in zip(corners, ids.ravel()):
                found[int(i)] = c[0]
        if all(i in found for i in self.corner_ids):
            src = [tuple(found[i].mean(0)) for i in self.corner_ids]
            H = homography_dlt(src, [(0, 0), (1, 0), (1, 1), (0, 1)])
            if H is not None:
                self.H = H
        toks = []
        if self.H is not None:
            for i, c in found.items():
                if i in self.corner_ids:
                    continue
                pts = [h_apply(self.H, float(x), float(y)) for x, y in c]
                cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
                ang = math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
                toks.append({"kind": "token", "id": i, "x": cx, "y": cy, "angle": ang, "w": abs(pts[1][0] - pts[0][0]) + 0.01, "h": abs(pts[3][1] - pts[0][1]) + 0.01})
        return {"tokens": toks, "calibrated": self.H is not None, "seen": sorted(found)}

    def close(self):
        with self.lock:
            self.cap.release()


def marker_sheet_svg(ids=range(0, 24), size_mm=35.0, cols=4) -> str:
    """Printable true-scale sheet of ArUco MIP 36h12 markers (0–3 = desk corners)."""
    if cv2 is None:
        raise RuntimeError("needs opencv-contrib-python")
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_ARUCO_MIP_36h12)
    cell = size_mm + 20
    rows = math.ceil(len(list(ids)) / cols)
    W, H = cols * cell + 20, rows * cell + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">', f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<text x="10" y="12" font-family="sans-serif" font-size="5">TABULA-Ω tokens · ArUco MIP 36h12 · {size_mm:.0f} mm · print at 100 % · 0–3 go on the projected image corners (TL, TR, BR, BL)</text>']
    for n, mid in enumerate(ids):
        img = cv2.aruco.generateImageMarker(d, int(mid), 8)                         # 6×6 bits + 1-cell border = 8 cells, 1 px each
        px = size_mm / 8
        ox, oy = 10 + (n % cols) * cell, 20 + (n // cols) * cell
        out.append(f'<g transform="translate({ox},{oy})">')
        for y in range(8):
            for x in range(8):
                if img[y, x] < 128:
                    out.append(f'<rect x="{x * px:.3f}" y="{y * px:.3f}" width="{px + 0.01:.3f}" height="{px + 0.01:.3f}" fill="black"/>')
        label = {0: "corner TL", 1: "corner TR", 2: "corner BR", 3: "corner BL"}.get(mid, f"id {mid}")
        out.append(f'<text x="0" y="{size_mm + 6}" font-family="sans-serif" font-size="4">{label}</text></g>')
    out.append("</svg>")
    return "\n".join(out)


class TapCal:
    """Generic raw-sensor → desk calibration: the page shows 9 rings; the user touches each and holds still."""
    TARGETS = [(fx, fy) for fy in (0.2, 0.52, 0.84) for fx in (0.1, 0.5, 0.9)]

    LIFT_FRAMES = 3                                            # the finger must leave the surface between targets

    def __init__(self):
        self.i, self.samples, self.hold, self.done = 0, [], [], False
        self.need_lift, self.lift = False, 0

    def feed(self, raw_points, t):
        """raw_points: list of (x, y) touching points this frame → returns 'next' when a target was captured"""
        if self.done:
            return None
        if self.need_lift:                                     # a finger still resting on the last ring must not become the next sample
            self.lift = self.lift + 1 if not raw_points else 0
            if self.lift >= self.LIFT_FRAMES:
                self.need_lift = False
            return None
        if len(raw_points) != 1:
            self.hold = []
            return None
        p = raw_points[0]
        if self.hold and math.dist(self.hold[0][1], p) > 6:
            self.hold = []
        self.hold.append((t, p))
        if t - self.hold[0][0] >= 0.6:
            xs = [q[1][0] for q in self.hold]
            ys = [q[1][1] for q in self.hold]
            self.samples.append(((sum(xs) / len(xs), sum(ys) / len(ys)), self.TARGETS[self.i]))
            self.hold, self.i = [], self.i + 1
            self.need_lift, self.lift = True, 0
            if self.i >= len(self.TARGETS):
                self.done = True
            return "next"
        return None

    def solve(self):
        H, idx, rms = homography_ransac([s[0] for s in self.samples], [s[1] for s in self.samples], thresh=0.02)
        return H, rms, len(idx)


class TUIOIn:
    """Listens for TUIO 1.1 (/tuio/2Dcur, /tuio/2Dobj) — lets any external tracker (reacTIVision, CCV, OAK-D apps…) drive the desk."""

    def __init__(self, port=3333):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.5)
        self.cur, self.obj = {}, {}

    def poll(self):
        try:
            data, _ = self.sock.recvfrom(65536)
        except socket.timeout:
            return None
        except OSError:                                        # closed by stop_sense
            return None
        try:
            msgs = osc_parse(data)
        except Exception:                                      # one malformed datagram must not kill the listener
            return True
        for addr, args in msgs:
            try:
                if not args:
                    continue
                if addr == "/tuio/2Dcur":
                    if args[0] == "alive":
                        alive = set(args[1:])
                        self.cur = {k: v for k, v in self.cur.items() if k in alive}
                    elif args[0] == "set" and len(args) >= 4:
                        x, y = float(args[2]), float(args[3])
                        if math.isfinite(x) and math.isfinite(y):
                            self.cur[args[1]] = (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))
                elif addr == "/tuio/2Dobj":
                    if args[0] == "alive":
                        alive = set(args[1:])
                        self.obj = {k: v for k, v in self.obj.items() if k in alive}
                    elif args[0] == "set" and len(args) >= 6:
                        x, y, a = float(args[3]), float(args[4]), float(args[5])
                        if math.isfinite(x) and math.isfinite(y) and math.isfinite(a):
                            self.obj[args[1]] = (int(args[2]), min(1.0, max(0.0, x)), min(1.0, max(0.0, y)), a)
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        return True

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def tuio_frame(contacts, fseq, source="tabula@localhost") -> bytes:
    msgs = [osc_message("/tuio/2Dcur", "source", source), osc_message("/tuio/2Dcur", "alive", *[int(c["id"]) for c in contacts])]
    for c in contacts:
        msgs.append(osc_message("/tuio/2Dcur", "set", int(c["id"]), float(c["x"]), float(c["y"]), 0.0, 0.0, 0.0))
    msgs.append(osc_message("/tuio/2Dcur", "fseq", int(fseq)))
    return osc_bundle(*msgs)
