"""
Kill switch.

Turns off the two things that act on their own - autonomous learning (chat
answers becoming learned knowledge, retraining, sleep cycles) and autonomous
actions (anything PermissionGuard would run) - without taking chat down.
Set from the admin API, or forced from the environment
(KILL_SWITCH_LEARNING=1 / KILL_SWITCH_ACTIONS=1), in which case the API
cannot switch it back on.
"""
import os
import threading
import time

from config import DATA_DIR
from control.store import read_json, write_json


def _env_on(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes", "on")


class KillSwitch:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(DATA_DIR, "killswitch.json")
        self._lock = threading.RLock()
        saved = read_json(self.path, {})
        self._state = {
            "learning_enabled": bool(saved.get("learning_enabled", True)),
            "actions_enabled": bool(saved.get("actions_enabled", True)),
            "reason": saved.get("reason", ""),
            "changed_by": saved.get("changed_by", ""),
            "changed_at": saved.get("changed_at"),
        }

    def learning_allowed(self) -> bool:
        return self._state["learning_enabled"] and not _env_on("KILL_SWITCH_LEARNING")

    def actions_allowed(self) -> bool:
        return self._state["actions_enabled"] and not _env_on("KILL_SWITCH_ACTIONS")

    def set(self, *, learning: bool | None = None, actions: bool | None = None,
            reason: str = "", by: str = "admin") -> dict:
        with self._lock:
            if learning is not None:
                self._state["learning_enabled"] = bool(learning)
            if actions is not None:
                self._state["actions_enabled"] = bool(actions)
            self._state.update(reason=reason[:300], changed_by=by, changed_at=int(time.time()))
            write_json(self.path, self._state)
            return self.status()

    def status(self) -> dict:
        return {
            "learning_enabled": self.learning_allowed(),
            "actions_enabled": self.actions_allowed(),
            "forced_by_env": {
                "learning": _env_on("KILL_SWITCH_LEARNING"),
                "actions": _env_on("KILL_SWITCH_ACTIONS"),
            },
            "reason": self._state["reason"],
            "changed_by": self._state["changed_by"],
            "changed_at": self._state["changed_at"],
        }