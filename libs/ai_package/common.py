"""
common.py
~~~~~~~~~
Shared perception + control utilities used by every task logic module
(gate_logic.py, slalom_logic.py, ...) so they don't duplicate/drift on the
same DB-schema assumptions and control primitives.
"""

import math
import time
from datetime import datetime
from typing import Iterable, Optional, Tuple

from ..config import get_env
from ..quick_request import AUVClient


# ---------------------------------------------------------------------------
# DB schema field names -- confirmed against quick_request.py / zed_camera.py
# ---------------------------------------------------------------------------

DEPTH_FIELD = "DEPTH"
GYRO_Z_FIELD = "GYRO_Z"

DET_CLASS_FIELD = "CLASS_NAME"
DET_CONF_FIELD = "CONFIDENCE"
DET_BBOX_X_FIELD = "BBOX_X"
DET_BBOX_Y_FIELD = "BBOX_Y"
DET_BBOX_W_FIELD = "BBOX_W"
DET_BBOX_H_FIELD = "BBOX_H"
DET_DISTANCE_FIELD = "DISTANCE"       # confirmed meters (sl.UNIT.METER)
DET_TIMESTAMP_FIELD = "TIMESTAMP"     # assumed present based on list()'s start/end docs

# ZED 2i nominal FOV -- real value depends on resolution mode + per-unit
# calibration. Pull the real numbers via zed.get_camera_information()...
# left_cam.h_fov / v_fov and set these env vars accordingly.
CAM_HFOV_DEG = float(get_env("CAM_HFOV_DEG", "110"))
CAM_VFOV_DEG = float(get_env("CAM_VFOV_DEG", "70"))


# ---------------------------------------------------------------------------
# Detection fetching
# ---------------------------------------------------------------------------

def row_epoch(row: dict) -> Optional[float]:
    ts = row.get(DET_TIMESTAMP_FIELD)
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fetch_recent_detections(client: AUVClient, lookback_rows: int,
                             max_age_s: float, conf_threshold: float) -> list:
    """Return recent, non-stale, sufficiently-confident detection rows (any class)."""
    try:
        page = client.list("detections", limit=lookback_rows) or {}
    except Exception:
        return []

    rows = page.get("items", [])
    now = time.time()
    out = []
    for row in rows:
        conf = float(row.get(DET_CONF_FIELD, 0.0) or 0.0)
        if conf < conf_threshold:
            continue
        t = row_epoch(row)
        if t is not None and (now - t) > max_age_s:
            continue
        out.append(row)
    return out


def best_row_for_classes(rows: Iterable[dict], classes: set) -> Optional[dict]:
    """Highest-confidence row whose CLASS_NAME is in `classes`."""
    best = None
    for row in rows:
        if row.get(DET_CLASS_FIELD) in classes:
            conf = float(row.get(DET_CONF_FIELD, 0.0) or 0.0)
            if best is None or conf > float(best.get(DET_CONF_FIELD, 0.0)):
                best = row
    return best


def bbox_center_norm(row: dict) -> Tuple[float, float]:
    bx = float(row[DET_BBOX_X_FIELD])
    by = float(row[DET_BBOX_Y_FIELD])
    bw = float(row[DET_BBOX_W_FIELD])
    bh = float(row[DET_BBOX_H_FIELD])
    return bx + bw / 2.0, by + bh / 2.0


def valid_range(row: dict, max_plausible_m: float, min_plausible_m: float = 0.0) -> Optional[float]:
    """
    zed_camera.py posts DISTANCE = -1.0 when the depth lookup failed/was
    non-finite -- never trust that. Also reject implausibly large readings
    (bbox center often lands on open water/background behind an object with
    a hole in it, e.g. gate or between poles) and implausibly small ones if
    a min is given (useful to ignore a pole you've already passed).
    """
    d = row.get(DET_DISTANCE_FIELD)
    if d is None:
        return None
    d = float(d)
    return d if min_plausible_m < d <= max_plausible_m else None


def normalized_to_bearing_elevation(u_norm: float, v_norm: float,
                                     hfov_rad: Optional[float] = None,
                                     vfov_rad: Optional[float] = None) -> Tuple[float, float]:
    """bearing > 0 => target to the right; elevation > 0 => target above camera center."""
    hfov_rad = hfov_rad if hfov_rad is not None else math.radians(CAM_HFOV_DEG)
    vfov_rad = vfov_rad if vfov_rad is not None else math.radians(CAM_VFOV_DEG)
    bearing = math.atan((u_norm - 0.5) * 2.0 * math.tan(hfov_rad / 2.0))
    elevation = math.atan((0.5 - v_norm) * 2.0 * math.tan(vfov_rad / 2.0))
    return bearing, elevation


# ---------------------------------------------------------------------------
# Filtering / control primitives
# ---------------------------------------------------------------------------

class EMAFilter:
    def __init__(self, alpha: float):
        self.alpha = alpha
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else (self.alpha * x + (1 - self.alpha) * self.value)
        return self.value


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