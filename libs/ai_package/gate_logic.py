"""
gate_logic.py
~~~~~~~~~~~~~
Gate traversal task. Exposes the standard task-module interface used by
ai_manager.py:

    TASK_CLASSES        -- set of CLASS_NAME values this task cares about
    reset()              -- reinitialize state for a fresh run
    is_done() -> bool     -- has this task finished
    peek(client) -> float -- best current confidence for this task's classes,
                             0.0 if none seen recently (cheap, no state change)
    update(client) -> dict -- run one control cycle, return an inputs dict
"""

import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

from ..config import get_env
from ..quick_request import AUVClient
from . import common
from .common import EMAFilter, PID, best_row_for_classes, bbox_center_norm, valid_range

# ---------------------------------------------------------------------------
# !!! CONFIRM/ADJUST THESE !!!
# ---------------------------------------------------------------------------

# Confirmed from data.yaml (nc: 7, names: [..., 'Gate', ...]) -- CLASS_NAME is
# posted as the string from result.names[cls_id], i.e. literally "Gate".
GATE_CLASSES = {"Gate"}
TASK_CLASSES = GATE_CLASSES

# Optional: only set these if your model has two distinct classes marking
# the left/right side of the gate. Leave None to skip true yaw-plane
# alignment and fall back to bearing-only centering in ALIGN.
GATE_LEFT_REF_CLASS: Optional[str] = None
GATE_RIGHT_REF_CLASS: Optional[str] = None

DET_CONF_THRESHOLD = float(get_env("GATE_DET_CONF_THRESHOLD", "0.5"))
DET_LOOKBACK_ROWS = int(get_env("GATE_DET_LOOKBACK_ROWS", "8"))
DET_MAX_AGE_S = float(get_env("GATE_DET_MAX_AGE_S", "0.5"))

# The "Gate" bbox center pixel often lands in open water inside the gate
# frame, not on the physical structure -- the ZED depth sample there can
# pick up the pool floor / far wall behind the gate. Reject readings past
# a plausible pool distance rather than trusting them.
DET_MAX_PLAUSIBLE_RANGE_M = float(get_env("GATE_DET_MAX_PLAUSIBLE_RANGE_M", "8.0"))

GATE_WIDTH_M = float(get_env("GATE_WIDTH_M", "3.0"))
TARGET_DEPTH_M = float(get_env("GATE_TARGET_DEPTH_M", "1.0"))

TRAVERSE_SECONDS = float(get_env("GATE_TRAVERSE_SECONDS", "6.0"))
MAX_SURGE_APPROACH = float(get_env("GATE_MAX_SURGE_APPROACH", "0.5"))
MAX_SURGE_TRAVERSE = float(get_env("GATE_MAX_SURGE_TRAVERSE", "0.6"))

YAW_RATE_DAMPING_GAIN = float(get_env("GATE_YAW_RATE_DAMPING_GAIN", "0.1"))


# ---------------------------------------------------------------------------
# Detection -> estimate
# ---------------------------------------------------------------------------

@dataclass
class GateDetection:
    found: bool
    bbox_center_norm: Tuple[float, float] = (0.5, 0.5)
    confidence: float = 0.0
    distance_m: Optional[float] = None
    left_distance_m: Optional[float] = None
    right_distance_m: Optional[float] = None


def fetch_gate_detection(client: AUVClient) -> GateDetection:
    rows = common.fetch_recent_detections(client, DET_LOOKBACK_ROWS, DET_MAX_AGE_S, DET_CONF_THRESHOLD)

    best_row = best_row_for_classes(rows, GATE_CLASSES)
    left_row = best_row_for_classes(rows, {GATE_LEFT_REF_CLASS}) if GATE_LEFT_REF_CLASS else None
    right_row = best_row_for_classes(rows, {GATE_RIGHT_REF_CLASS}) if GATE_RIGHT_REF_CLASS else None

    if best_row is None:
        return GateDetection(found=False)

    center_norm = bbox_center_norm(best_row)
    dist = valid_range(best_row, DET_MAX_PLAUSIBLE_RANGE_M)
    left_dist = valid_range(left_row, DET_MAX_PLAUSIBLE_RANGE_M) if left_row else None
    right_dist = valid_range(right_row, DET_MAX_PLAUSIBLE_RANGE_M) if right_row else None

    return GateDetection(
        found=True,
        bbox_center_norm=center_norm,
        confidence=float(best_row.get(common.DET_CONF_FIELD, 0.0)),
        distance_m=dist,
        left_distance_m=left_dist,
        right_distance_m=right_dist,
    )


@dataclass
class GateEstimate:
    bearing_rad: float = 0.0
    elevation_rad: float = 0.0
    range_m: float = 3.0
    yaw_offset_rad: float = 0.0
    valid: bool = False


class GateTracker:
    def __init__(self, alpha: float = 0.3):
        self.bearing_f = EMAFilter(alpha)
        self.elev_f = EMAFilter(alpha)
        self.range_f = EMAFilter(alpha)
        self.yaw_f = EMAFilter(alpha)
        self.estimate = GateEstimate()

    def update(self, det: GateDetection) -> GateEstimate:
        if not det.found:
            self.estimate.valid = False
            return self.estimate

        u, v = det.bbox_center_norm
        bearing, elevation = common.normalized_to_bearing_elevation(u, v)
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
                target_err = est.yaw_offset_rad if (GATE_LEFT_REF_CLASS and GATE_RIGHT_REF_CLASS) else est.bearing_rad
                yaw = self.align_pid.update(target_err, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                aligned = abs(target_err) < self.cfg.yaw_align_tol_rad
            else:
                aligned = True

            if aligned:
                self._aligned_since = self._aligned_since or now
                if now - self._aligned_since > self.cfg.align_hold_time_s:
                    self._traverse_start_t = now
                    self._enter(State.COMMIT_TRAVERSE)
            else:
                self._aligned_since = None

        elif self.state == State.COMMIT_TRAVERSE:
            surge = self.cfg.max_surge_traverse
            yaw = -YAW_RATE_DAMPING_GAIN * yaw_rate
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

        return {"ARM": 1, "SURGE": surge, "SWAY": sway, "HEAVE": heave, "YAW": yaw}


# ---------------------------------------------------------------------------
# Standard task-module interface (used by ai_manager.py)
# ---------------------------------------------------------------------------

_tracker = GateTracker()
_traverser = GateTraverser(_tracker, GateConfig())


def reset() -> None:
    global _tracker, _traverser
    _tracker = GateTracker()
    _traverser = GateTraverser(_tracker, GateConfig())


def is_done() -> bool:
    return _traverser.state == State.DONE


def peek(client: AUVClient) -> float:
    """Cheap check: best current confidence for this task's classes, else 0."""
    rows = common.fetch_recent_detections(client, DET_LOOKBACK_ROWS, DET_MAX_AGE_S, 0.0)
    row = best_row_for_classes(rows, TASK_CLASSES)
    return float(row.get(common.DET_CONF_FIELD, 0.0)) if row else 0.0


def update(client: AUVClient) -> dict:
    """Run one control cycle. This is what ai_manager.py calls each poll."""
    imu = client.latest("imu") or {}
    depth_row = client.latest("depth") or {}

    depth = float(depth_row.get(common.DEPTH_FIELD, TARGET_DEPTH_M))
    yaw_rate = float(imu.get(common.GYRO_Z_FIELD, 0.0) or 0.0)
    det = fetch_gate_detection(client)

    return _traverser.update(det, depth, yaw_rate)


# ---------------------------------------------------------------------------
# Tuning note
# ---------------------------------------------------------------------------
# MAX_SURGE_APPROACH / MAX_SURGE_TRAVERSE / TRAVERSE_SECONDS are placeholders.
# Empirically tune: command a fixed SURGE value in a straight line for a
# measured time in the pool, measure distance traveled, back out effective
# m/s at that command, then set TRAVERSE_SECONDS = desired_distance_m /
# measured_speed_mps with a margin.