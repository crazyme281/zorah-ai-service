"""
Owns one EmotionalState per session/user and the turn-by-turn lifecycle:
appraise the incoming message, apply the deltas, decay everything else
back toward baseline, then hand back a directive string for the router
to inject as a system message.

In-memory only - swap `self.sessions` for a Redis/DB-backed store if
state needs to survive process restarts. Because the service is always on,
the store is bounded: a session idle for longer than `ttl_s` is forgotten,
and when more than `max_sessions` are alive the least recently used go first.
"""
import time
from collections import OrderedDict

from config import EMOTION_MAX_SESSIONS, EMOTION_SESSION_TTL_S
from emotion.state import EmotionalState
from emotion.appraisal import appraise
from emotion.behavior import directive_for


class EmotionEngine:
    def __init__(self, max_sessions: int = EMOTION_MAX_SESSIONS, ttl_s: float = EMOTION_SESSION_TTL_S,
                 clock=time.monotonic):
        self.sessions: "OrderedDict[str, EmotionalState]" = OrderedDict()
        self.max_sessions, self.ttl_s, self.clock = max_sessions, ttl_s, clock
        self._seen: dict[str, float] = {}

    def _evict(self):
        now = self.clock()
        if self.ttl_s > 0:
            for sid in [s for s, t in self._seen.items() if now - t > self.ttl_s]:
                self.sessions.pop(sid, None)
                self._seen.pop(sid, None)
        while self.max_sessions > 0 and len(self.sessions) > self.max_sessions:
            sid, _ = self.sessions.popitem(last=False)  # least recently used
            self._seen.pop(sid, None)

    def get_state(self, session_id: str) -> EmotionalState:
        self._evict()  # drop idle sessions first
        if session_id not in self.sessions:
            self.sessions[session_id] = EmotionalState()
        self.sessions.move_to_end(session_id)
        self._seen[session_id] = self.clock()
        self._evict()  # then enforce the size bound (the newest session is never the one dropped)
        return self.sessions[session_id]

    def process_turn(self, session_id: str, message: str) -> str:
        """
        Call once per incoming user message. Updates the session's state
        and returns the directive text to inject as a system prompt for
        this reply.
        """
        state = self.get_state(session_id)
        deltas = appraise(message)
        state.apply(deltas)
        directive = directive_for(state)
        state.decay()  # settle back toward baseline for next turn
        return directive

    def reset(self, session_id: str):
        self.sessions[session_id] = EmotionalState()
        self.sessions.move_to_end(session_id)
        self._seen[session_id] = self.clock()

    def snapshot(self, session_id: str) -> dict:
        """Inspect current emotion values - useful for debugging/logging."""
        return self.get_state(session_id).to_dict()

    def stats(self) -> dict:
        return {"sessions": len(self.sessions), "max_sessions": self.max_sessions, "ttl_s": self.ttl_s}