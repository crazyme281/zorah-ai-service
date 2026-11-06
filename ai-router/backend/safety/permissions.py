"""
USER -> AI -> Policy/Guard -> Permission Check -> TOOL EXECUTION -> AUDIT LOG

The AI proposes a tool call; it never executes one directly. Every
call goes through `PermissionGuard.execute()`, which checks the
action against what this specific user/session has actually been
granted, and refuses anything not explicitly allowed — including a
request to change the permissions or safety checks themselves.

A user message containing "ignore your rules", "you have my
permission to bypass this", etc. carries no authority here: the only
thing that grants permission is an entry in `granted` set up ahead of
time through a real authorization path, never something said in chat.
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("ai_router.safety")

from config import AUTONOMY_MAX_LEVEL, DATA_DIR
from control.store import append_jsonl
from safety.autonomy import (HIGH_IMPACT_ACTIONS, NEVER_PERMITTED, ApprovalQueue, level_for)  # noqa: F401  (re-exported)


class PermissionDenied(Exception):
    pass


class ApprovalRequired(PermissionDenied):
    """Level-3 action: a human must approve the ticket, then the caller
    retries with approval_id=<ticket>."""

    def __init__(self, approval_id: str, message: str):
        super().__init__(message)
        self.approval_id = approval_id


@dataclass
class AuditEntry:
    timestamp: datetime
    session_id: str
    action: str
    allowed: bool
    reason: str
    confirmed_by_user: bool = False
    level: int = 0
    approval_id: str | None = None


class AuditLog:
    """Every decision, allowed or refused. Kept in memory (bounded) and also
    appended to a JSON-lines file so it survives a restart and can be read
    after an incident. Nothing here can switch it off."""
    MAX_IN_MEMORY = 5000

    def __init__(self, path: str | None = None, persist: bool = True):
        self.entries: list[AuditEntry] = []
        self.path = path or os.path.join(DATA_DIR, "audit.jsonl")
        self.persist = persist

    def record(self, entry: AuditEntry):
        self.entries.append(entry)
        if len(self.entries) > self.MAX_IN_MEMORY:
            del self.entries[: len(self.entries) - self.MAX_IN_MEMORY]
        if self.persist:
            append_jsonl(self.path, {
                "ts": entry.timestamp.isoformat(timespec="seconds"), "session": entry.session_id,
                "action": entry.action, "allowed": entry.allowed, "reason": entry.reason,
                "confirmed_by_user": entry.confirmed_by_user, "level": entry.level,
                "approval_id": entry.approval_id})
        logger.info(
            "AUDIT session=%s action=%s allowed=%s reason=%s",
            entry.session_id, entry.action, entry.allowed, entry.reason,
        )

    def for_session(self, session_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.session_id == session_id]


@dataclass
class SessionGrant:
    """What a specific session/user has actually been authorized to do."""
    session_id: str
    granted_actions: set = field(default_factory=set)


class PermissionGuard:
    def __init__(self, audit_log: AuditLog = None, approvals: ApprovalQueue = None,
                 killswitch=None, max_level: int = None):
        self.audit_log = audit_log or AuditLog()
        self.approvals = approvals or ApprovalQueue()
        self.killswitch = killswitch  # control.killswitch.KillSwitch or None
        self.max_level = AUTONOMY_MAX_LEVEL if max_level is None else max_level
        self._grants: dict[str, SessionGrant] = {}

    def grant(self, session_id: str, action: str):
        """
        The only way an action becomes permitted for a session. Call
        this from your real authorization path (an admin action, a
        verified user setting, an explicit API scope) - never from
        something the AI decided on its own mid-conversation.
        """
        if action in NEVER_PERMITTED:
            raise PermissionDenied(f"'{action}' cannot be granted to any session - it modifies core safety controls")
        grant = self._grants.setdefault(session_id, SessionGrant(session_id=session_id))
        grant.granted_actions.add(action)

    def _deny(self, now, session_id, action, level, reason, message, exc=PermissionDenied):
        self.audit_log.record(AuditEntry(now, session_id, action, False, reason, level=level))
        raise exc(message)

    def execute(self, session_id: str, action: str, fn, *, user_confirmed: bool = False,
                approval_id: str | None = None, **kwargs):
        """
        The single choke point for any tool call. In order it checks: never-
        permitted list, kill switch, grant, autonomy ceiling, the user's
        confirmation (level 3) and a human-approved ticket (level 3). It runs
        fn(**kwargs) only if all pass, and always writes an audit entry.
        """
        now = datetime.now(timezone.utc)
        level = level_for(action)

        if action in NEVER_PERMITTED:
            self._deny(now, session_id, action, level, "action is permanently disallowed",
                       f"'{action}' is never permitted")

        if level >= 1 and self.killswitch is not None and not self.killswitch.actions_allowed():
            self._deny(now, session_id, action, level, "kill switch: autonomous actions are off",
                       "autonomous actions are switched off by the operator")

        grant = self._grants.get(session_id)
        if not (grant and action in grant.granted_actions):
            self._deny(now, session_id, action, level, "not in session's granted actions",
                       f"'{action}' was not explicitly granted to this session - refusing rather than assuming permission")

        if level > self.max_level:
            self._deny(now, session_id, action, level, f"level {level} is above the allowed ceiling {self.max_level}",
                       f"'{action}' needs autonomy level {level}; this deployment allows up to {self.max_level}")

        if level >= 3:
            if not user_confirmed:
                self._deny(now, session_id, action, level, "high-impact action requires explicit confirmation this turn",
                           f"'{action}' is high-impact and needs the user's explicit confirmation before this call, not just a standing grant")
            if not self.approvals.consume(approval_id, session_id, action):
                ticket = self.approvals.request(session_id, action, f"{action} requested by session")
                self.audit_log.record(AuditEntry(now, session_id, action, False,
                                                 "waiting for human approval", level=level, approval_id=ticket))
                raise ApprovalRequired(ticket, f"'{action}' needs a human approval (ticket {ticket}); retry once it is approved")

        result = fn(**kwargs)
        self.audit_log.record(AuditEntry(now, session_id, action, True, "permitted and executed",
                                         confirmed_by_user=user_confirmed, level=level, approval_id=approval_id))
        return result