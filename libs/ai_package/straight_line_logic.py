"""
straight_run_logic.py
~~~~~~~~~~~~~~~~~~~~~~
Utility task: drive straight for a fixed distance while holding depth
(whatever depth the sub is at when the run starts) and heading (via
short-term gyro integration, since there's no vision target here to
correct against).

Not part of MISSION_PLAN / the gate-slalom task switching -- this is a
standalone diagnostic/calibration tool, dispatched separately by
ai_manager.py via AI_MODE=straight_run. It's also the natural tool to use
for the "measure real speed at a given SURGE command" calibration step
mentioned in gate_logic.py / slalom_logic.py's tuning notes.

No vision required, so TASK_CLASSES is empty and peek() always returns 0 --
this task should never participate in the manager's vision-based override
logic.

Exposes the same interface shape as the other task modules:
    TASK_CLASSES, reset(), is_done(), peek(client), update(client)
"""

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from ..config import get_env
from ..quick_request import AUVClient
from . import common
from .common import PID

TASK_CLASSES: set = set()  # no vision involved

FT_TO_M = 0.3048
STRAIGHT_RUN_DISTANCE_FT = float(get_env("STRAIGHT_RUN_DISTANCE_FT", "10.0"))
STRAIGHT_RUN_DISTANCE_M = STRAIGHT_RUN_DISTANCE_FT * FT_TO_M

STRAIGHT_RUN_SURGE = float(get_env("STRAIGHT_RUN_SURGE", "0.4"))

# Estimated speed (m/s) at STRAIGHT_RUN_SURGE -- a guess until you've
# actually measured it. Used only if STRAIGHT_RUN_SECONDS_OVERRIDE is unset.
STRAIGHT_RUN_SPEED_ESTIMATE_MPS = float(get_env("STRAIGHT_RUN_SPEED_ESTIMATE_MPS", "0.4"))

# Set this once you've measured real speed at STRAIGHT_RUN_SURGE, to skip
# the estimate entirely and just run for a known-good duration.
_seconds_override = get_env("STRAIGHT_RUN_SECONDS_OVERRIDE", "")
STRAIGHT_RUN_SECONDS_OVERRIDE: Optional[float] = float(_seconds_override) if _seconds_override else None


class State(Enum):
    RUNNING = auto()
    DONE = auto()


class StraightRunner:
    def __init__(self):
        self.state = State.RUNNING
        self.depth_pid = PID(kp=0.8, ki=0.05, kd=0.1)
        self.heading_pid = PID(kp=0.6, ki=0.0, kd=0.1)

        self._start_t: Optional[float] = None
        self._target_depth: Optional[float] = None
        self._integrated_yaw = 0.0
        self._last_t: Optional[float] = None

        if STRAIGHT_RUN_SECONDS_OVERRIDE is not None:
            self._run_seconds = STRAIGHT_RUN_SECONDS_OVERRIDE
        else:
            self._run_seconds = STRAIGHT_RUN_DISTANCE_M / max(STRAIGHT_RUN_SPEED_ESTIMATE_MPS, 1e-3)

    def update(self, current_depth: float, yaw_rate: float) -> dict:
        now = time.time()

        if self.state == State.DONE:
            return {"ARM": 1, "SURGE": 0.0, "SWAY": 0.0, "HEAVE": 0.0, "YAW": 0.0}

        if self._start_t is None:
            self._start_t = now
            self._target_depth = current_depth  # "maintain the same height" = hold whatever depth we start at
            self._last_t = now

        dt = max(1e-3, now - self._last_t)
        self._integrated_yaw += yaw_rate * dt
        self._last_t = now

        heave = self.depth_pid.update(self._target_depth - current_depth, now)
        yaw = self.heading_pid.update(-self._integrated_yaw, now)  # correct drift back toward 0

        if now - self._start_t >= self._run_seconds:
            self.state = State.DONE
            return {"ARM": 1, "SURGE": 0.0, "SWAY": 0.0, "HEAVE": heave, "YAW": 0.0}

        return {"ARM": 1, "SURGE": STRAIGHT_RUN_SURGE, "SWAY": 0.0, "HEAVE": heave, "YAW": yaw}


# ---------------------------------------------------------------------------
# Standard task-module interface
# ---------------------------------------------------------------------------

_runner = StraightRunner()


def reset() -> None:
    global _runner
    _runner = StraightRunner()


def is_done() -> bool:
    return _runner.state == State.DONE


def peek(client: AUVClient) -> float:
    """No vision target for this task -- never worth switching into via override."""
    return 0.0


def update(client: AUVClient) -> dict:
    imu = client.latest("imu") or {}
    depth_row = client.latest("depth") or {}

    depth = float(depth_row.get(common.DEPTH_FIELD, 0.0))
    yaw_rate = float(imu.get(common.GYRO_Z_FIELD, 0.0) or 0.0)

    return _runner.update(depth, yaw_rate)