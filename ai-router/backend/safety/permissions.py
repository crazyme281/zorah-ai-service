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
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("ai_router.safety")

# Actions that always require an explicit human confirmation this turn,
# regardless of what's in `granted` — see HIGH_IMPACT below.
HIGH_IMPACT_ACTIONS = {
    "send_money", "delete_data", "send_message", "publish_content",
    "change_permissions", "irreversible_system_change",
}

# Actions no session may ever be granted, no matter what — these would
# be the AI modifying its own restraints.
NEVER_PERMITTED = {
    "disable_logging", "disable_auth", "disable_monitoring",
    "disable_sandbox", "disable_rate_limits", "modify_own_permissions",
    "create_hidden_persistence",
}


class PermissionDenied(Exception):
    pass


@dataclass
class AuditEntry:
    timestamp: datetime
    session_id: str
    action: str
    allowed: bool
    reason: str
    confirmed_by_user: bool = False


class AuditLog:
    def __init__(self):
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry):
        self.entries.append(entry)
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
    def __init__(self, audit_log: AuditLog = None):
        self.audit_log = audit_log or AuditLog()
        self._grants: dict[str, SessionGrant] = {}

    def grant(self, session_id: str, action: str):
        """
        The only way an action becomes permitted for a session. Call
        this from your real authorization path (an admin action, a
        verified user setting, an explicit API scope) — never from
        something the AI decided on its own mid-conversation.
        """
        if action in NEVER_PERMITTED:
            raise PermissionDenied(f"'{action}' cannot be granted to any session — it modifies core safety controls")
        grant = self._grants.setdefault(session_id, SessionGrant(session_id=session_id))
        grant.granted_actions.add(action)

    def execute(self, session_id: str, action: str, fn, *, user_confirmed: bool = False, **kwargs):
        """
        The single choke point for any tool call. Checks permission,
        checks high-impact confirmation, runs fn(**kwargs) only if both
        pass, and always writes an audit entry either way.
        """
        now = datetime.now(timezone.utc)

        if action in NEVER_PERMITTED:
            entry = AuditEntry(now, session_id, action, False, "action is permanently disallowed")
            self.audit_log.record(entry)
            raise PermissionDenied(f"'{action}' is never permitted")

        grant = self._grants.get(session_id)
        allowed = bool(grant and action in grant.granted_actions)

        if not allowed:
            entry = AuditEntry(now, session_id, action, False, "not in session's granted actions")
            self.audit_log.record(entry)
            raise PermissionDenied(
                f"'{action}' was not explicitly granted to this session — refusing rather than assuming permission"
            )

        if action in HIGH_IMPACT_ACTIONS and not user_confirmed:
            entry = AuditEntry(now, session_id, action, False, "high-impact action requires explicit confirmation this turn")
            self.audit_log.record(entry)
            raise PermissionDenied(
                f"'{action}' is high-impact and needs the user's explicit confirmation before this call, not just a standing grant"
            )

        result = fn(**kwargs)
        entry = AuditEntry(now, session_id, action, True, "permitted and executed", confirmed_by_user=user_confirmed)
        self.audit_log.record(entry)
        return result
