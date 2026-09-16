"""
Emotional state for a single conversation/session.

Each emotion is tracked as an intensity 0.0-1.0 rather than a single
mood label, because real reactions blend (you can be embarrassed AND
a little angry at once). trust and respect_felt are longer-running
attitudes toward this specific user, so they decay far slower than
the reactive emotions like anger or fear.
"""
from dataclasses import dataclass, asdict


# How fast each field drifts back toward its baseline every turn, when
# nothing new pushes it further. Reactive emotions fade fast; trust and
# respect are stickier because they're built up over a relationship.
DECAY_RATES = {
    "joy": 0.25,
    "anger": 0.20,
    "fear": 0.30,
    "embarrassment": 0.35,
    "attraction": 0.10,
    "jealousy": 0.20,
    "desire": 0.20,
    "trust": 0.05,
    "respect_felt": 0.05,
    "threatened": 0.25,
}

BASELINE = {
    "joy": 0.3,
    "anger": 0.0,
    "fear": 0.0,
    "embarrassment": 0.0,
    "attraction": 0.0,
    "jealousy": 0.0,
    "desire": 0.0,
    "trust": 0.5,
    "respect_felt": 0.5,
    "threatened": 0.0,
}


@dataclass
class EmotionalState:
    joy: float = 0.3
    anger: float = 0.0
    fear: float = 0.0
    embarrassment: float = 0.0
    attraction: float = 0.0
    jealousy: float = 0.0
    desire: float = 0.0
    trust: float = 0.5          # 0 = total stranger-distrust, 1 = fully trusted
    respect_felt: float = 0.5   # how respected the AI feels by this user
    threatened: float = 0.0
    turns: int = 0

    def clamp(self):
        for field in DECAY_RATES:
            val = getattr(self, field)
            setattr(self, field, max(0.0, min(1.0, val)))

    def apply(self, deltas: dict):
        """Add deltas (e.g. {'anger': 0.3, 'trust': -0.1}) to current state."""
        for key, delta in deltas.items():
            if key in DECAY_RATES:
                setattr(self, key, getattr(self, key) + delta)
        self.clamp()

    def decay(self):
        """Pull every field a step back toward baseline. Call once per turn."""
        for field, rate in DECAY_RATES.items():
            current = getattr(self, field)
            base = BASELINE[field]
            setattr(self, field, current + (base - current) * rate)
        self.turns += 1
        self.clamp()

    def dominant(self, threshold: float = 0.4, max_emotions: int = 2) -> list[str]:
        """
        Return the reactive emotions currently strong enough to shape behavior,
        strongest first. trust/respect_felt are excluded here since they're
        background attitudes, handled separately in behavior.py.
        """
        reactive = ["joy", "anger", "fear", "embarrassment", "attraction", "jealousy", "desire", "threatened"]
        scored = [(f, getattr(self, f)) for f in reactive if getattr(self, f) >= threshold]
        scored.sort(key=lambda x: -x[1])
        return [f for f, _ in scored[:max_emotions]]

    def to_dict(self) -> dict:
        return asdict(self)
