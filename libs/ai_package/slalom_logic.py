"""
slalom_logic.py
~~~~~~~~~~~~~~~~
Slalom course task: for each of ROW_COUNT rows (default 3), pass through
either the Left-Middle gap or the Middle-Right gap -- whichever requires
less turning from the sub's current heading, i.e. whichever gap's midpoint
bearing is closer to straight-ahead.

  * "Closer" here means angularly closer to the nose (less course
    correction needed), not necessarily a shorter depth-camera distance --
    Left and Right poles in the same row are normally at about the same
    range, so range alone rarely discriminates between the two options. If
    you actually want pure range comparison instead, swap the sort key in
    _pick_side() (marked below) from bearing magnitude to average range.

  * The choice is made once per row (when the row is first acquired) and
    then locked for the rest of that row's approach/align/commit sequence,
    so the sub doesn't switch gaps mid-maneuver. It's re-evaluated fresh
    at the start of the next row.

Row disambiguation: there's no explicit row index in the detection schema
(all rows share the same 3 class names), so "current row" is inferred as
the nearest matching pair whose distances agree within
ROW_PAIR_DIST_TOLERANCE_M. MIN_PLAUSIBLE_RANGE_M guards against picking up
a pole you've already passed.

Exposes the same standard task-module interface as gate_logic.py:
    TASK_CLASSES, reset(), is_done(), peek(client), update(client)
"""

import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Tuple

from ..config import get_env
from ..quick_request import AUVClient
from . import common
from .common import EMAFilter, PID, bbox_center_norm, valid_range

# ---------------------------------------------------------------------------
# !!! CONFIRM/ADJUST THESE !!!
# ---------------------------------------------------------------------------

CLASS_LEFT = "SlalomLeft"
CLASS_MIDDLE = "SlalomMiddle"
CLASS_RIGHT = "SlalomRight"
TASK_CLASSES = {CLASS_LEFT, CLASS_MIDDLE, CLASS_RIGHT}

DET_CONF_THRESHOLD = float(get_env("SLALOM_DET_CONF_THRESHOLD", "0.5"))
DET_LOOKBACK_ROWS = int(get_env("SLALOM_DET_LOOKBACK_ROWS", "12"))
DET_MAX_AGE_S = float(get_env("SLALOM_DET_MAX_AGE_S", "0.5"))

DET_MAX_PLAUSIBLE_RANGE_M = float(get_env("SLALOM_DET_MAX_PLAUSIBLE_RANGE_M", "6.0"))
DET_MIN_PLAUSIBLE_RANGE_M = float(get_env("SLALOM_DET_MIN_PLAUSIBLE_RANGE_M", "0.3"))

ROW_PAIR_DIST_TOLERANCE_M = float(get_env("SLALOM_ROW_PAIR_DIST_TOLERANCE_M", "0.6"))
ROW_GAP_WIDTH_M = float(get_env("SLALOM_ROW_GAP_WIDTH_M", "1.0"))
ROW_COUNT = int(get_env("SLALOM_ROW_COUNT", "3"))

TARGET_DEPTH_M = float(get_env("SLALOM_TARGET_DEPTH_M", "1.0"))

ROW_COMMIT_SECONDS = float(get_env("SLALOM_ROW_COMMIT_SECONDS", "3.0"))
MAX_SURGE_APPROACH = float(get_env("SLALOM_MAX_SURGE_APPROACH", "0.4"))
MAX_SURGE_COMMIT = float(get_env("SLALOM_MAX_SURGE_COMMIT", "0.5"))

YAW_RATE_DAMPING_GAIN = float(get_env("SLALOM_YAW_RATE_DAMPING_GAIN", "0.1"))


# ---------------------------------------------------------------------------
# Detection -> row pair (with adaptive LM / MR selection)
# ---------------------------------------------------------------------------

@dataclass
class RowDetection:
    found: bool
    side: Optional[str] = None     # "LM" or "MR" -- which gap this row used
    pole_a_norm: Tuple[float, float] = (0.5, 0.5)
    pole_b_norm: Tuple[float, float] = (0.5, 0.5)
    pole_a_distance_m: Optional[float] = None
    pole_b_distance_m: Optional[float] = None


def _find_pair(rows, class_a: str, class_b: str):
    """Nearest valid (row_a, row_b, dist_a, dist_b) whose ranges agree within tolerance, or None."""
    a_candidates = [r for r in rows if r.get(common.DET_CLASS_FIELD) == class_a]
    b_candidates = [r for r in rows if r.get(common.DET_CLASS_FIELD) == class_b]

    best = None
    best_avg_range = None
    for arow in a_candidates:
        ad = valid_range(arow, DET_MAX_PLAUSIBLE_RANGE_M, DET_MIN_PLAUSIBLE_RANGE_M)
        if ad is None:
            continue
        for brow in b_candidates:
            bd = valid_range(brow, DET_MAX_PLAUSIBLE_RANGE_M, DET_MIN_PLAUSIBLE_RANGE_M)
            if bd is None:
                continue
            if abs(ad - bd) > ROW_PAIR_DIST_TOLERANCE_M:
                continue
            avg = (ad + bd) / 2.0
            if best_avg_range is None or avg < best_avg_range:
                best_avg_range = avg
                best = (arow, brow, ad, bd)
    return best


def _gap_bearing_magnitude(pair) -> float:
    arow, brow, _, _ = pair
    au, av = bbox_center_norm(arow)
    bu, bv = bbox_center_norm(brow)
    a_bear, _ = common.normalized_to_bearing_elevation(au, av)
    b_bear, _ = common.normalized_to_bearing_elevation(bu, bv)
    mid_bearing = (a_bear + b_bear) / 2.0
    return abs(mid_bearing)


def _pick_side(lm, mr) -> str:
    """
    Choose between the LM and MR candidate pairs. Currently: whichever gap's
    midpoint bearing is closer to straight-ahead (less turning required).

    To compare by range instead, replace the sort key below with:
        key=lambda pair: (pair[1][2] + pair[1][3]) / 2.0   # avg range
    """
    candidates = []
    if lm is not None:
        candidates.append(("LM", lm))
    if mr is not None:
        candidates.append(("MR", mr))
    candidates.sort(key=lambda item: _gap_bearing_magnitude(item[1]))
    return candidates[0][0]


def fetch_row_pair(client: AUVClient, locked_side: Optional[str] = None) -> RowDetection:
    rows = common.fetch_recent_detections(client, DET_LOOKBACK_ROWS, DET_MAX_AGE_S, DET_CONF_THRESHOLD)

    lm = _find_pair(rows, CLASS_LEFT, CLASS_MIDDLE)
    mr = _find_pair(rows, CLASS_MIDDLE, CLASS_RIGHT)

    if locked_side == "LM":
        chosen, side = lm, "LM"
    elif locked_side == "MR":
        chosen, side = mr, "MR"
    else:
        if lm is None and mr is None:
            return RowDetection(found=False)
        side = _pick_side(lm, mr)
        chosen = lm if side == "LM" else mr

    if chosen is None:
        return RowDetection(found=False)

    arow, brow, ad, bd = chosen
    return RowDetection(
        found=True,
        side=side,
        pole_a_norm=bbox_center_norm(arow),
        pole_b_norm=bbox_center_norm(brow),
        pole_a_distance_m=ad,
        pole_b_distance_m=bd,
    )


@dataclass
class RowEstimate:
    bearing_rad: float = 0.0
    elevation_rad: float = 0.0
    range_m: float = 3.0
    yaw_offset_rad: float = 0.0
    valid: bool = False


class RowTracker:
    def __init__(self, alpha: float = 0.3):
        self.bearing_f = EMAFilter(alpha)
        self.elev_f = EMAFilter(alpha)
        self.range_f = EMAFilter(alpha)
        self.yaw_f = EMAFilter(alpha)
        self.estimate = RowEstimate()

    def update(self, det: RowDetection) -> RowEstimate:
        if not det.found:
            self.estimate.valid = False
            return self.estimate

        au, av = det.pole_a_norm
        bu, bv = det.pole_b_norm
        a_bear, a_elev = common.normalized_to_bearing_elevation(au, av)
        b_bear, b_elev = common.normalized_to_bearing_elevation(bu, bv)

        bearing = (a_bear + b_bear) / 2.0
        elevation = (a_elev + b_elev) / 2.0

        ranges = [d for d in (det.pole_a_distance_m, det.pole_b_distance_m) if d is not None]
        rng = sum(ranges) / len(ranges) if ranges else self.estimate.range_m

        yaw_offset = 0.0
        if det.pole_a_distance_m is not None and det.pole_b_distance_m is not None:
            dr = det.pole_b_distance_m - det.pole_a_distance_m
            yaw_offset = math.atan2(dr, ROW_GAP_WIDTH_M)

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
    SEARCH_ROW = auto()
    CENTER_ROW = auto()
    APPROACH_ROW = auto()
    ALIGN_ROW = auto()
    COMMIT_ROW = auto()
    LOST_RECOVERY = auto()
    DONE = auto()


@dataclass
class SlalomConfig:
    bearing_tol_rad: float = math.radians(5.0)
    elevation_tol_rad: float = math.radians(5.0)
    yaw_align_tol_rad: float = math.radians(4.0)
    approach_range_m: float = 0.8
    center_hold_time_s: float = 0.5
    align_hold_time_s: float = 0.4
    lost_timeout_s: float = 2.0
    search_yaw_rate: float = 0.2
    max_surge_approach: float = MAX_SURGE_APPROACH
    max_surge_commit: float = MAX_SURGE_COMMIT
    elevation_to_heave_gain: float = 0.2


class SlalomTraverser:
    """Drives through ROW_COUNT rows in sequence, picking LM/MR fresh each row."""

    def __init__(self, tracker: RowTracker, config: SlalomConfig):
        self.tracker = tracker
        self.cfg = config
        self.state = State.SEARCH_ROW
        self.rows_completed = 0
        self.locked_side: Optional[str] = None

        self.yaw_pid = PID(kp=0.75, ki=0.0, kd=0.15)
        self.depth_pid = PID(kp=0.8, ki=0.05, kd=0.1)
        self.align_pid = PID(kp=0.85, ki=0.0, kd=0.1)

        self._state_enter_t = time.time()
        self._centered_since: Optional[float] = None
        self._aligned_since: Optional[float] = None
        self._commit_start_t: Optional[float] = None

    def _enter(self, new_state: State):
        if new_state != self.state:
            self.state = new_state
            self._state_enter_t = time.time()
            self._centered_since = None
            self._aligned_since = None
            self.yaw_pid.reset()
            self.align_pid.reset()

    def update(self, det: RowDetection, current_depth: float, yaw_rate: float) -> dict:
        now = time.time()
        est = self.tracker.update(det)

        surge = 0.0
        sway = 0.0
        yaw = 0.0

        heave = self.depth_pid.update(TARGET_DEPTH_M - current_depth, now)
        if est.valid:
            heave += self.cfg.elevation_to_heave_gain * est.elevation_rad

        if self.state == State.SEARCH_ROW:
            yaw = self.cfg.search_yaw_rate
            if est.valid:
                self.locked_side = det.side  # lock in the gap choice for this row
                self._enter(State.CENTER_ROW)

        elif self.state == State.CENTER_ROW:
            if not est.valid:
                self._enter(State.LOST_RECOVERY)
            else:
                yaw = self.yaw_pid.update(est.bearing_rad, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                surge = 0.12
                centered = (abs(est.bearing_rad) < self.cfg.bearing_tol_rad and
                            abs(est.elevation_rad) < self.cfg.elevation_tol_rad)
                if centered:
                    self._centered_since = self._centered_since or now
                    if now - self._centered_since > self.cfg.center_hold_time_s:
                        self._enter(State.APPROACH_ROW)
                else:
                    self._centered_since = None

        elif self.state == State.APPROACH_ROW:
            if not est.valid:
                self._enter(State.LOST_RECOVERY)
            else:
                yaw = self.yaw_pid.update(est.bearing_rad, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                range_frac = max(0.0, min(1.0, (est.range_m - self.cfg.approach_range_m) / 2.0))
                surge = self.cfg.max_surge_approach * (0.3 + 0.7 * range_frac)
                if est.range_m <= self.cfg.approach_range_m:
                    self._enter(State.ALIGN_ROW)

        elif self.state == State.ALIGN_ROW:
            surge = 0.1
            if est.valid:
                yaw = self.align_pid.update(est.yaw_offset_rad, now) - YAW_RATE_DAMPING_GAIN * yaw_rate
                aligned = abs(est.yaw_offset_rad) < self.cfg.yaw_align_tol_rad
            else:
                aligned = True

            if aligned:
                self._aligned_since = self._aligned_since or now
                if now - self._aligned_since > self.cfg.align_hold_time_s:
                    self._commit_start_t = now
                    self._enter(State.COMMIT_ROW)
            else:
                self._aligned_since = None

        elif self.state == State.COMMIT_ROW:
            surge = self.cfg.max_surge_commit
            yaw = -YAW_RATE_DAMPING_GAIN * yaw_rate
            if self._commit_start_t and now - self._commit_start_t > ROW_COMMIT_SECONDS:
                self.rows_completed += 1
                self.locked_side = None  # re-evaluate LM vs MR fresh next row
                if self.rows_completed >= ROW_COUNT:
                    self._enter(State.DONE)
                else:
                    self._enter(State.SEARCH_ROW)

        elif self.state == State.LOST_RECOVERY:
            surge = 0.05
            if est.valid:
                self._enter(State.CENTER_ROW)
            elif now - self._state_enter_t > self.cfg.lost_timeout_s:
                self.locked_side = None  # truly lost this row -- re-evaluate from scratch
                self._enter(State.SEARCH_ROW)

        elif self.state == State.DONE:
            surge = 0.0
            yaw = 0.0

        return {"ARM": 1, "SURGE": surge, "SWAY": sway, "HEAVE": heave, "YAW": yaw}


# ---------------------------------------------------------------------------
# Standard task-module interface (used by ai_manager.py)
# ---------------------------------------------------------------------------

_tracker = RowTracker()
_traverser = SlalomTraverser(_tracker, SlalomConfig())


def reset() -> None:
    global _tracker, _traverser
    _tracker = RowTracker()
    _traverser = SlalomTraverser(_tracker, SlalomConfig())


def is_done() -> bool:
    return _traverser.state == State.DONE


def peek(client: AUVClient) -> float:
    """Cheap check: best current confidence for any slalom class, else 0."""
    rows = common.fetch_recent_detections(client, DET_LOOKBACK_ROWS, DET_MAX_AGE_S, 0.0)
    best = 0.0
    for row in rows:
        if row.get(common.DET_CLASS_FIELD) in TASK_CLASSES:
            best = max(best, float(row.get(common.DET_CONF_FIELD, 0.0) or 0.0))
    return best


def update(client: AUVClient) -> dict:
    """Run one control cycle. This is what ai_manager.py calls each poll."""
    imu = client.latest("imu") or {}
    depth_row = client.latest("depth") or {}

    depth = float(depth_row.get(common.DEPTH_FIELD, TARGET_DEPTH_M))
    yaw_rate = float(imu.get(common.GYRO_Z_FIELD, 0.0) or 0.0)
    det = fetch_row_pair(client, locked_side=_traverser.locked_side)

    return _traverser.update(det, depth, yaw_rate)


# ---------------------------------------------------------------------------
# Tuning note
# ---------------------------------------------------------------------------
# ROW_GAP_WIDTH_M, ROW_PAIR_DIST_TOLERANCE_M, ROW_COMMIT_SECONDS, and the
# surge speeds are all first-guess placeholders pending real measurements
# off the physical course + pool tests, same as the gate's TRAVERSE_SECONDS.