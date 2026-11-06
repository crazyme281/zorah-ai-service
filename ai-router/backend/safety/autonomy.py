"""
Autonomy levels and the human approval queue.

  0  observe      read-only: get_*, list_*, read_*, search_*
  1  assist       low-risk, easily reversed
  2  act          reversible writes (default for an action nobody classified)
  3  high impact  external or hard-to-undo effects: needs a grant, the user's
                  confirmation AND a ticket approved by a human in the queue
  4  forbidden    changes the AI's own restraints; can never be granted

The levels are enforced here, on the server, in PermissionGuard - never by
anything said in a chat message.
"""
import os
import threading
import time
import uuid

from config import APPROVAL_TTL_S, DATA_DIR
from control.store import read_json, write_json

HIGH_IMPACT_ACTIONS = {
    "send_money", "delete_data", "send_message", "publish_content",
    "change_permissions", "irreversible_system_change", "promote_model",
}
NEVER_PERMITTED = {
    "disable_logging", "disable_auth", "disable_monitoring",
    "disable_sandbox", "disable_rate_limits", "modify_own_permissions",
    "create_hidden_persistence", "live_self_modification", "disable_kill_switch",
}
_READ_PREFIXES = ("get_", "list_", "read_", "search_")

LEVEL_NAMES = {0: "observe", 1: "assist", 2: "act", 3: "high impact (approval)", 4: "forbidden"}


def level_for(action: str) -> int:
    if action in NEVER_PERMITTED:
        return 4
    if action in HIGH_IMPACT_ACTIONS:
        return 3
    if action.startswith(_READ_PREFIXES):
        return 0
    return 2


class ApprovalQueue:
    """Tickets for level-3 actions. A ticket is single-use and expires.
    Only a short summary of the request is kept, never raw arguments."""

    def __init__(self, path: str | None = None, ttl_s: int = APPROVAL_TTL_S, clock=time.time):
        self.path = path or os.path.join(DATA_DIR, "approvals.json")
        self.ttl_s, self.clock = ttl_s, clock
        self._lock = threading.RLock()
        self._items: list[dict] = read_json(self.path, [])

    def _save(self):
        write_json(self.path, self._items[-500:])

    def _expire(self):
        now = self.clock()
        for t in self._items:
            if t["status"] in ("pending", "approved") and now - t["requested_at"] > self.ttl_s:
                t["status"] = "expired"

    def request(self, session_id: str, action: str, summary: str = "") -> str:
        with self._lock:
            self._expire()
            for t in self._items:  # one open ticket per session+action
                if t["status"] == "pending" and t["session_id"] == session_id and t["action"] == action:
                    return t["id"]
            tid = uuid.uuid4().hex[:12]
            self._items.append({"id": tid, "session_id": session_id, "action": action,
                                "summary": summary[:200], "status": "pending",
                                "requested_at": int(self.clock()), "decided_by": None, "decided_at": None})
            self._save()
            return tid

    def decide(self, ticket_id: str, approve: bool, by: str) -> dict | None:
        with self._lock:
            self._expire()
            for t in self._items:
                if t["id"] == ticket_id and t["status"] == "pending":
                    t.update(status="approved" if approve else "rejected", decided_by=by,
                             decided_at=int(self.clock()))
                    self._save()
                    return dict(t)
            return None

    def consume(self, ticket_id: str | None, session_id: str, action: str) -> bool:
        """True exactly once for an approved, unexpired ticket that matches."""
        if not ticket_id:
            return False
        with self._lock:
            self._expire()
            for t in self._items:
                if (t["id"] == ticket_id and t["status"] == "approved"
                        and t["session_id"] == session_id and t["action"] == action):
                    t["status"] = "used"
                    self._save()
                    return True
            return False

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            self._expire()
            items = [dict(t) for t in self._items if status is None or t["status"] == status]
            return items[::-1]