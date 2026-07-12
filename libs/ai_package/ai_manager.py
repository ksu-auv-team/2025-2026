"""
ai_manager.py
~~~~~~~~~~~~~
Sequences task logic modules (gate_logic, slalom_logic, ...) into a mission.

Behavior (per your "hybrid" choice):
  - Normally runs tasks in the order given in MISSION_PLAN, advancing to the
    next task once the current one reports is_done().
  - If the active task hasn't seen its own target class(es) in a while
    (STUCK_TIMEOUT_S) AND a later task in the plan is clearly visible
    (peek() confidence above OVERRIDE_CONF_THRESHOLD), skip ahead to that
    task early rather than waiting/searching indefinitely.

Each task module must expose:
    TASK_CLASSES        -- set[str]
    reset() -> None
    is_done() -> bool
    peek(client) -> float          (0.0 if nothing seen recently)
    update(client) -> dict         (one control cycle, returns inputs dict)

Add new tasks by importing the module and adding it to MISSION_PLAN below.
"""

import time
from dataclasses import dataclass
from typing import List

from ..quick_request import AUVClient
from ..config import get_env
from . import gate_logic
from . import slalom_logic


@dataclass
class TaskEntry:
    name: str
    module: object


# Default run order. Change this list (and only this list) to reorder or
# add tasks -- everything else in this file is generic.
MISSION_PLAN: List[TaskEntry] = [
    TaskEntry("gate", gate_logic),
    #TaskEntry("slalom", slalom_logic),
]

# How long the active task can go without seeing its own target before
# it's considered "stuck" and eligible to be skipped past.
STUCK_TIMEOUT_S = float(get_env("MANAGER_STUCK_TIMEOUT_S", "4.0"))

# Confidence a later task's peek() must clear to be worth jumping to early.
OVERRIDE_CONF_THRESHOLD = float(get_env("MANAGER_OVERRIDE_CONF_THRESHOLD", "0.6"))

# Don't run peek() on every single control cycle (it costs an extra DB
# query per idle task) -- only check this often.
OVERRIDE_CHECK_INTERVAL_S = float(get_env("MANAGER_OVERRIDE_CHECK_INTERVAL_S", "1.0"))


class AIManager:
    def __init__(self, plan: List[TaskEntry]):
        self.plan = plan
        self.index = 0
        self.plan[0].module.reset()

        self._last_own_visible_t = time.time()
        self._last_override_check_t = 0.0

    def _current(self) -> TaskEntry:
        return self.plan[self.index]

    def _advance_to(self, new_index: int) -> None:
        if new_index != self.index and 0 <= new_index < len(self.plan):
            self.index = new_index
            self.plan[new_index].module.reset()
            self._last_own_visible_t = time.time()

    def _maybe_override(self, client: AUVClient, now: float) -> None:
        if now - self._last_override_check_t < OVERRIDE_CHECK_INTERVAL_S:
            return
        self._last_override_check_t = now

        current_conf = self._current().module.peek(client)
        if current_conf > 0.0:
            self._last_own_visible_t = now
            return  # current task is fine, no need to consider skipping

        if now - self._last_own_visible_t < STUCK_TIMEOUT_S:
            return  # not stuck long enough yet

        # Current task appears stuck. Check later tasks for something
        # clearly visible worth jumping to.
        for i in range(self.index + 1, len(self.plan)):
            conf = self.plan[i].module.peek(client)
            if conf >= OVERRIDE_CONF_THRESHOLD:
                self._advance_to(i)
                return

    def update(self, client: AUVClient) -> dict:
        now = time.time()

        # Natural sequential progression.
        while self._current().module.is_done() and self.index < len(self.plan) - 1:
            self._advance_to(self.index + 1)

        if self._current().module.is_done():
            # Mission complete: hold station rather than cut thrust outright.
            # Swap this for a disarm/surface behavior if that's what you want
            # at the end of a run.
            return {"ARM": 1, "SURGE": 0.0, "SWAY": 0.0, "HEAVE": 0.0, "YAW": 0.0}

        self._maybe_override(client, now)

        return self._current().module.update(client)


_manager = AIManager(MISSION_PLAN)


def update(client: AUVClient) -> dict:
    """Entry point called from ai_interface.run()."""
    return _manager.update(client)


def reset() -> None:
    global _manager
    _manager = AIManager(MISSION_PLAN)


def current_task_name() -> str:
    return _manager._current().name