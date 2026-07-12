## FOR QUALIFIERS AND GATE - NEED NEW LOGIC CODE FOR SLALOM

"""
ai_logic.py
~~~~~~~~~~~
Autonomous behavior logic, called once per cycle from ai_interface.run().

Pulls imu/depth/detections straight from the AUVClient and returns an
`inputs` dict shaped like the manual controller's inputs (SURGE/SWAY/HEAVE/
YAW/ARM/...), fed straight into movement_package.generate_outputs().

Currently implements: gate traversal only.

IMPORTANT NOTES ON YOUR ACTUAL SCHEMA
--------------------------------------
- `detections` is one row PER detected object, not one row summarizing the
  whole frame. `client.latest("detections")` gives you whatever object was
  posted last, which may not be the gate if multiple things are visible
  in-frame. So this module pulls the last N rows with client.list() and
  filters by CLASS_NAME instead of trusting latest().
- bbox_x/y/w/h are already normalized [0,1], top-left origin (per your
  detector.py). No pixel intrinsics needed -- just camera FOV.
- There's no separate left/right post distance in your schema. True gate-
  plane yaw alignment needs two distinct reference detections (e.g. two
  known symbol/marker classes on either side of the gate, or two pole
  classes) -- wire GATE_LEFT_REF_CLASS / GATE_RIGHT_REF_CLASS below if your
  model has them. Otherwise ALIGN just does a final centered-bearing check
  instead of true perpendicularity, which is usually fine given gate width
  tolerances but is a real simplification -- flagging it so it's a known
  tradeoff and not a silent one.
"""

import math
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Tuple

from ..config import get_env
from ..quick_request import AUVClient


# ---------------------------------------------------------------------------
# !!! CONFIRM/ADJUST THESE !!!
# ---------------------------------------------------------------------------

DEPTH_FIELD = "DEPTH"          # confirmed via quick_request.py docstring
GYRO_Z_FIELD = "GYRO_Z"        # confirmed via quick_request.py docstring

DET_CLASS_FIELD = "CLASS_NAME"        # confirmed via your _post() snippet
DET_CONF_FIELD = "CONFIDENCE"
DET_BBOX_X_FIELD = "BBOX_X"
DET_BBOX_Y_FIELD = "BBOX_Y"
DET_BBOX_W_FIELD = "BBOX_W"
DET_BBOX_H_FIELD = "BBOX_H"
DET_DISTANCE_FIELD = "DISTANCE"       # confirmed meters (init.coordinate_units = sl.UNIT.METER)
DET_TIMESTAMP_FIELD = "TIMESTAMP"     # assumed present based on list()'s start/end docs

# Confirmed from data.yaml (nc: 7, names: [..., 'Gate', ...]) -- CLASS_NAME is
# posted as the string from result.names[cls_id], i.e. literally "Gate".
GATE_CLASSES = {"Gate"}

# Optional: only set these if your model has two distinct classes marking
# the left/right side of the gate (e.g. two symbols, two posts). Leave None
# to skip true yaw-plane alignment and fall back to bearing-only centering.
GATE_LEFT_REF_CLASS: Optional[str] = None
GATE_RIGHT_REF_CLASS: Optional[str] = None

DET_CONF_THRESHOLD = float(get_env("GATE_DET_CONF_THRESHOLD", "0.5"))
DET_LOOKBACK_ROWS = int(get_env("GATE_DET_LOOKBACK_ROWS", "8"))
DET_MAX_AGE_S = float(get_env("GATE_DET_MAX_AGE_S", "0.5"))  # ignore stale rows if TIMESTAMP present

# The "Gate" bbox center pixel often lands in open water inside the gate
# frame, not on the physical structure -- the ZED depth sample there can
# pick up the pool floor / far wall behind the gate instead of the gate's
# real distance. Treat readings beyond a plausible pool distance as bad data
# rather than trusting them. Tune this to your actual pool/course size.
DET_MAX_PLAUSIBLE_RANGE_M = float(get_env("GATE_DET_MAX_PLAUSIBLE_RANGE_M", "8.0"))

# Nominal ZED 2i spec is 110(H) x 70(V), but that's the max/diagonal-lens
# figure and real usable FOV depends on resolution mode (you're running
# HD1080) and per-unit calibration. Get the real numbers instead of trusting
# these defaults -- in zed_camera.py, after zed.open(init) succeeds, add:
#     calib = zed.get_camera_information().camera_configuration.calibration_parameters.left_cam
#     log.info(f"h_fov={calib.h_fov} v_fov={calib.v_fov}")
# then set GATE_CAM_HFOV_DEG / GATE_CAM_VFOV_DEG env vars to the logged values.
CAM_HFOV_DEG = float(get_env("CAM_HFOV_DEG", "110"))
CAM_VFOV_DEG = float(get_env("CAM_VFOV_DEG", "70"))

GATE_WIDTH_M = float(get_env("GATE_WIDTH_M", "3.0"))
TARGET_DEPTH_M = float(get_env("GATE_TARGET_DEPTH_M", "1.0"))

# Empirically tune these against real pool tests -- see note at bottom of file.
TRAVERSE_SECONDS = float(get_env("GATE_TRAVERSE_SECONDS", "6.0"))
MAX_SURGE_APPROACH = float(get_env("GATE_MAX_SURGE_APPROACH", "0.5"))
MAX_SURGE_TRAVERSE = float(get_env("GATE_MAX_SURGE_TRAVERSE", "0.6"))

YAW_RATE_DAMPING_GAIN = float(get_env("GATE_YAW_RATE_DAMPING_GAIN", "0.1"))


# ---------------------------------------------------------------------------
# Detection fetch + parsing
# ---------------------------------------------------------------------------

@dataclass
class GateDetection:
    found: bool
    bbox_center_norm: Tuple[float, float] = (0.5, 0.5)
    confidence: float = 0.0
    distance_m: Optional[float] = None
    left_distance_m: Optional[float] = None
    right_distance_m: Optional[float] = None


def _row_epoch(row: dict) -> Optional[float]:
    ts = row.get(DET_TIMESTAMP_FIELD)
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fetch_gate_detection(client: AUVClient) -> GateDetection:
    """
    Pull the last few detection rows and pick the best current gate
    detection (and optional left/right reference rows for yaw alignment).
    """
    try:
        page = client.list("detections", limit=DET_LOOKBACK_ROWS) or {}
    except Exception:
        return GateDetection(found=False)

    rows = page.get("items", [])
    now = time.time()

    best_row = None
    left_row = None
    right_row = None

    for row in rows:
        conf = float(row.get(DET_CONF_FIELD, 0.0) or 0.0)
        if conf < DET_CONF_THRESHOLD:
            continue

        row_t = _row_epoch(row)
        if row_t is not None and (now - row_t) > DET_MAX_AGE_S:
            continue  # stale -- gate no longer in view this cycle

        cls = row.get(DET_CLASS_FIELD)

        if cls in GATE_CLASSES:
            if best_row is None or conf > float(best_row.get(DET_CONF_FIELD, 0.0)):
                best_row = row
        if GATE_LEFT_REF_CLASS and cls == GATE_LEFT_REF_CLASS:
            left_row = row
        if GATE_RIGHT_REF_CLASS and cls == GATE_RIGHT_REF_CLASS:
            right_row = row

    if best_row is None:
        return GateDetection(found=False)

    bx = float(best_row[DET_BBOX_X_FIELD])
    by = float(best_row[DET_BBOX_Y_FIELD])
    bw = float(best_row[DET_BBOX_W_FIELD])
    bh = float(best_row[DET_BBOX_H_FIELD])
    center_norm = (bx + bw / 2.0, by + bh / 2.0)

    # zed_camera.py posts DISTANCE = -1.0 as a sentinel when the depth lookup
    # at the bbox center failed or was non-finite -- that must NOT be treated
    # as a real range reading.
    # zed_camera.py posts DISTANCE = -1.0 as a sentinel when the depth lookup
    # at the bbox center failed or was non-finite. Also reject anything past
    # DET_MAX_PLAUSIBLE_RANGE_M -- likely background seen through the open
    # gate frame rather than the gate's actual distance.
    def _valid_range(d):
        return d is not None and 0.0 < float(d) <= DET_MAX_PLAUSIBLE_RANGE_M

    dist = best_row.get(DET_DISTANCE_FIELD)
    left_dist = left_row.get(DET_DISTANCE_FIELD) if left_row else None
    right_dist = right_row.get(DET_DISTANCE_FIELD) if right_row else None

    return GateDetection(
        found=True,
        bbox_center_norm=center_norm,
        confidence=float(best_row.get(DET_CONF_FIELD, 0.0)),
        distance_m=float(dist) if _valid_range(dist) else None,
        left_distance_m=float(left_dist) if _valid_range(left_dist) else None,
        right_distance_m=float(right_dist) if _valid_range(right_dist) else None,
    )


def normalized_to_bearing_elevation(u_norm: float, v_norm: float,
                                     hfov_rad: float, vfov_rad: float) -> Tuple[float, float]:
    """bearing > 0 => gate to the right; elevation > 0 => gate above camera center."""
    bearing = math.atan((u_norm - 0.5) * 2.0 * math.tan(hfov_rad / 2.0))
    elevation = math.atan((0.5 - v_norm) * 2.0 * math.tan(vfov_rad / 2.0))
    return bearing, elevation


class EMAFilter:
    def __init__(self, alpha: float):
        self.alpha = alpha
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else (self.alpha * x + (1 - self.alpha) * self.value)
        return self.value


@dataclass
class GateEstimate:
    bearing_rad: float = 0.0
    elevation_rad: float = 0.0
    range_m: float = 3.0
    yaw_offset_rad: float = 0.0   # 0 unless GATE_LEFT/RIGHT_REF_CLASS are configured
    valid: bool = False


class GateTracker:
    def __init__(self, alpha: float = 0.3):
        self.bearing_f = EMAFilter(alpha)
        self.elev_f = EMAFilter(alpha)
        self.range_f = EMAFilter(alpha)
        self.yaw_f = EMAFilter(alpha)
        self.estimate = GateEstimate()
        self._hfov = math.radians(CAM_HFOV_DEG)
        self._vfov = math.radians(CAM_VFOV_DEG)

    def update(self, det: GateDetection) -> GateEstimate:
        if not det.found:
            self.estimate.valid = False
            return self.estimate

        u, v = det.bbox_center_norm
        bearing, elevation = normalized_to_bearing_elevation(u, v, self._hfov, self._vfov)
        rng = det.distance_m if det.distance_m is not None else self.estimate.range_m

        yaw_offset = 0.0
        if det.left_distance_m is not None and det.right_distance_m is not None:
            dr = det.right_distance_m - det.left_distance_m
            yaw_offset = math.atan2(dr, GATE_WIDTH_M)

        self.estimate.bearing_rad = self.bearing_f.update(bearing)
        self.estimate.elevation_rad = self.elev_f.update(elevation)
        self.estimate.range_m = self.range_f.update(rng)
        self.estimate.yaw_offset_rad = self.yaw_f.update(yaw_offset)
        self.estimate.valid = True
        return self.estimate


# ---------------------------------------------------------------------------
# PID
# ---------------------------------------------------------------------------

class PID:
    def __init__(self, kp, ki, kd, out_limits=(-1.0, 1.0), i_limit=None):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_limits
        self.i_limit = i_limit if i_limit is not None else self.out_max
        self._integral = 0.0
        self._prev_err = None
        self._prev_t = None

    def reset(self):
        self._integral = 0.0
        self._prev_err = None
        self._prev_t = None

    def update(self, error: float, now: float) -> float:
        dt = 0.0 if self._prev_t is None else max(1e-3, now - self._prev_t)
        self._integral = max(-self.i_limit, min(self.i_limit, self._integral + error * dt))
        deriv = 0.0 if self._prev_err is None or dt == 0 else (error - self._prev_err) / dt
        out = self.kp * error + self.ki * self._integral + self.kd * deriv
        self._prev_err = error
        self._prev_t = now
        return max(self.out_min, min(self.out_max, out))


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class State(Enum):
    SEARCH = auto()
    CENTER = auto()
    APPROACH = auto()
    ALIGN = auto()
    COMMIT_TRAVERSE = auto()
    LOST_RECOVERY = auto()
    DONE = auto()


@dataclass
class GateConfig:
    bearing_tol_rad: float = math.radians(4.0)
    elevation_tol_rad: float = math.radians(4.0)
    yaw_align_tol_rad: float = math.radians(3.0)
    approach_range_m: float = 1.2
    center_hold_time_s: float = 0.75
    align_hold_time_s: float = 0.5
    lost_timeout_s: float = 2.0
    search_yaw_rate: float = 0.25
    max_surge_approach: float = MAX_SURGE_APPROACH
    max_surge_traverse: float = MAX_SURGE_TRAVERSE
    elevation_to_heave_gain: float = 0.2


class GateTraverser:
    def __init__(self, tracker: GateTracker, config: GateConfig):
        self.tracker = tracker
        self.cfg = config
        self.state = State.SEARCH

        self.yaw_pid = PID(kp=0.8, ki=0.0, kd=0.15)
        self.depth_pid = PID(kp=0.8, ki=0.05, kd=0.1)
        self.align_pid = PID(kp=0.9, ki=0.0, kd=0.1)

        self._state_enter_t = time.time()
        self._centered_since: Optional[float] = None
        self._aligned_since: Optional[float] = None
        self._traverse_start_t: Optional[float] = None

    def _enter(self, new_state: State):
        if new_state != self.state:
            self.state = new_state
            self._state_enter_t = time.time()
            self._centered_since = None
            self._aligned_since = None
            self.yaw_pid.reset()
            self.align_pid.reset()

    def update(self, det: GateDetection, current_depth: float, yaw_rate: float) -> dict:
        now = time.time()
        est = self.tracker.update(det)

        surge = 0.0
        sway = 0.0
        yaw = 0.0

        # Depth-hold runs continuously, with a small vision nudge on top
        # while locked. Check sign against your sub -- flip if inverted.
        heave = self.depth_pid.update(TARGET_DEPTH_M - current_depth, now)
        if est.valid:
            heave += self.cfg.elevation_to_heave_gain * est.elevation_rad

        if self.state == State.SEARCH:
            yaw = self.cfg.search_yaw_rate
            if est.valid:
                self._enter(State.CENTER)

        elif self.state == State.CENTER:
            if not est.valid:
                self._enter(State.LOST_RECOVERY)
            else:
                yaw = self.yaw_pid.update(est.bearing_rad, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                surge = 0.15
                centered = (abs(est.bearing_rad) < self.cfg.bearing_tol_rad and
                            abs(est.elevation_rad) < self.cfg.elevation_tol_rad)
                if centered:
                    self._centered_since = self._centered_since or now
                    if now - self._centered_since > self.cfg.center_hold_time_s:
                        self._enter(State.APPROACH)
                else:
                    self._centered_since = None

        elif self.state == State.APPROACH:
            if not est.valid:
                self._enter(State.LOST_RECOVERY)
            else:
                yaw = self.yaw_pid.update(est.bearing_rad, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                range_frac = max(0.0, min(1.0, (est.range_m - self.cfg.approach_range_m) / 3.0))
                surge = self.cfg.max_surge_approach * (0.3 + 0.7 * range_frac)
                if est.range_m <= self.cfg.approach_range_m:
                    self._enter(State.ALIGN)

        elif self.state == State.ALIGN:
            surge = 0.1
            if est.valid:
                # If no left/right reference classes configured, yaw_offset_rad
                # is always 0 and this collapses to a final bearing check.
                target_err = est.yaw_offset_rad if (GATE_LEFT_REF_CLASS and GATE_RIGHT_REF_CLASS) else est.bearing_rad
                yaw = self.align_pid.update(target_err, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                aligned = abs(target_err) < self.cfg.yaw_align_tol_rad
            else:
                aligned = True  # vision dropping this close is expected

            if aligned:
                self._aligned_since = self._aligned_since or now
                if now - self._aligned_since > self.cfg.align_hold_time_s:
                    self._traverse_start_t = now
                    self._enter(State.COMMIT_TRAVERSE)
            else:
                self._aligned_since = None

        elif self.state == State.COMMIT_TRAVERSE:
            # Open loop -- no position sensor to measure real distance yet.
            surge = self.cfg.max_surge_traverse
            yaw = -YAW_RATE_DAMPING_GAIN * yaw_rate  # hold heading, damp drift
            if self._traverse_start_t and now - self._traverse_start_t > TRAVERSE_SECONDS:
                self._enter(State.DONE)

        elif self.state == State.LOST_RECOVERY:
            surge = 0.05
            if est.valid:
                self._enter(State.CENTER)
            elif now - self._state_enter_t > self.cfg.lost_timeout_s:
                self._enter(State.SEARCH)

        elif self.state == State.DONE:
            surge = 0.0
            yaw = 0.0

        return {
            "ARM": 1,
            "SURGE": surge,
            "SWAY": sway,
            "HEAVE": heave,
            "YAW": yaw,
        }


# ---------------------------------------------------------------------------
# Module-level instance + entry point called from ai_interface.run()
# ---------------------------------------------------------------------------

_tracker = GateTracker()
_traverser = GateTraverser(_tracker, GateConfig())


def ai_logic(client: AUVClient) -> dict:
    """Called once per control cycle from ai_interface.run()."""
    imu = client.latest("imu") or {}
    depth_row = client.latest("depth") or {}

    depth = float(depth_row.get(DEPTH_FIELD, TARGET_DEPTH_M))
    yaw_rate = float(imu.get(GYRO_Z_FIELD, 0.0) or 0.0)
    det = fetch_gate_detection(client)

    return _traverser.update(det, depth, yaw_rate)


def is_done() -> bool:
    return _traverser.state == State.DONE


# ---------------------------------------------------------------------------
# Tuning note
# ---------------------------------------------------------------------------
# MAX_SURGE_APPROACH / MAX_SURGE_TRAVERSE / TRAVERSE_SECONDS are placeholders.
# With ~19 kg mass and ~5.25 kgf max thrust per corner thruster but unknown
# drag/added-mass, I can't derive real speed-per-SURGE-command numbers from
# the physics sheet alone. Easiest path: command a fixed SURGE value in a
# straight line for a measured time in the pool, measure distance traveled,
# back out effective m/s at that command, then set TRAVERSE_SECONDS =
# desired_distance_m / measured_speed_mps with a margin.