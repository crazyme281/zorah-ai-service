"""
Owns one EmotionalState per session/user and the turn-by-turn lifecycle:
appraise the incoming message, apply the deltas, decay everything else
back toward baseline, then hand back a directive string for the router
to inject as a system message.

In-memory only — swap `self.sessions` for a Redis/DB-backed store if
state needs to survive process restarts.
"""
from emotion.state import EmotionalState
from emotion.appraisal import appraise
from emotion.behavior import directive_for


class EmotionEngine:
    def __init__(self):
        self.sessions: dict[str, EmotionalState] = {}

    def get_state(self, session_id: str) -> EmotionalState:
        if session_id not in self.sessions:
            self.sessions[session_id] = EmotionalState()
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

    def snapshot(self, session_id: str) -> dict:
        """Inspect current emotion values — useful for debugging/logging."""
        return self.get_state(session_id).to_dict()
