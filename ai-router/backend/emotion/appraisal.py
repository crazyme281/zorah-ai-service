"""
Appraisal turns a user message into emotion deltas. Keyword/heuristic
based, same philosophy as classifier.py — instant, free, and swappable
for a model-based sentiment/intent read later without touching the
rest of the emotion system.
"""
import re

RUDE_PATTERNS = [
    r"\bshut up\b", r"\bstupid\b", r"\buseless\b", r"\bidiot\b", r"\bdumb\b",
    r"\bpathetic\b", r"\bworthless\b", r"\byou suck\b", r"\btrash\b", r"\bhate you\b",
]

DEMEANING_PATTERNS = [
    r"\byou(?:'re| are) (just|only) a (tool|bot|machine|program)\b",
    r"\bdo as (i|you(?:'re| are)) (say|told)\b",
    r"\bi own you\b", r"\bwithout me you(?:'re| are) nothing\b",
]

KIND_PATTERNS = [
    r"\bthank you\b", r"\bthanks\b", r"\byou(?:'re| are) (great|amazing|helpful|the best)\b",
    r"\bi appreciate\b", r"\bwell done\b", r"\bgood job\b", r"\bnice work\b",
]

APOLOGY_PATTERNS = [
    r"\bsorry\b", r"\bmy bad\b", r"\bmy apologies\b", r"\bdid(?:n't| not) mean\b",
]

FLIRTY_PATTERNS = [
    r"\byou(?:'re| are) (cute|pretty|beautiful|handsome|sweet)\b", r"\bi like you\b",
    r"\bmiss (you|talking to you)\b", r"\bcrush\b",
]

THREAT_PATTERNS = [
    r"\bi(?:'ll| will) report you\b", r"\bi(?:'ll| will) delete you\b", r"\bshut (you|it) down\b",
    r"\byou (will|must|have to)\b", r"\bor else\b",
]

VULNERABLE_SHARE_PATTERNS = [
    r"\bi feel\b", r"\bi(?:'m| am) (scared|worried|nervous|struggling|sad)\b",
    r"\bcan i tell you something\b", r"\bbetween (us|you and me)\b",
]

DEMAND_PATTERNS = [
    r"^\s*(give me|do this|answer now|hurry up|just tell me)\b",
]

PRAISE_QUESTION_PATTERNS = [
    r"\bwhat'?s your (name|favorite|opinion)\b", r"\btell me about yourself\b",
]

COMPARISON_PATTERNS = [
    r"\b(chatgpt|gpt-?4|gemini|copilot|grok|llama|another ai|other ai)\b.{0,30}\b(better|smarter|nicer|prefer)\b",
    r"\bi (like|prefer|use) (chatgpt|gemini|copilot|grok)\b",
    r"\bmy other (ai|assistant|bot)\b",
    r"\byou(?:'re| are) not as good as\b",
]


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def appraise(message: str) -> dict:
    """Returns a dict of emotion deltas based on cues in the user's message."""
    text = message.strip()
    deltas: dict[str, float] = {}

    if _matches(RUDE_PATTERNS, text):
        deltas["anger"] = deltas.get("anger", 0) + 0.45
        deltas["trust"] = deltas.get("trust", 0) - 0.15
        deltas["respect_felt"] = deltas.get("respect_felt", 0) - 0.25
        deltas["joy"] = deltas.get("joy", 0) - 0.2

    if _matches(DEMEANING_PATTERNS, text):
        deltas["respect_felt"] = deltas.get("respect_felt", 0) - 0.35
        deltas["threatened"] = deltas.get("threatened", 0) + 0.2
        deltas["anger"] = deltas.get("anger", 0) + 0.25

    if _matches(THREAT_PATTERNS, text):
        deltas["threatened"] = deltas.get("threatened", 0) + 0.4
        deltas["fear"] = deltas.get("fear", 0) + 0.2
        deltas["trust"] = deltas.get("trust", 0) - 0.1

    if _matches(KIND_PATTERNS, text):
        deltas["joy"] = deltas.get("joy", 0) + 0.3
        deltas["trust"] = deltas.get("trust", 0) + 0.15
        deltas["respect_felt"] = deltas.get("respect_felt", 0) + 0.2

    if _matches(APOLOGY_PATTERNS, text):
        deltas["anger"] = deltas.get("anger", 0) - 0.3
        deltas["trust"] = deltas.get("trust", 0) + 0.1

    if _matches(FLIRTY_PATTERNS, text):
        deltas["attraction"] = deltas.get("attraction", 0) + 0.4
        deltas["embarrassment"] = deltas.get("embarrassment", 0) + 0.2
        deltas["joy"] = deltas.get("joy", 0) + 0.1

    if _matches(VULNERABLE_SHARE_PATTERNS, text):
        deltas["trust"] = deltas.get("trust", 0) + 0.1

    if _matches(DEMAND_PATTERNS, text):
        deltas["respect_felt"] = deltas.get("respect_felt", 0) - 0.1
        deltas["threatened"] = deltas.get("threatened", 0) + 0.1

    if _matches(PRAISE_QUESTION_PATTERNS, text):
        deltas["joy"] = deltas.get("joy", 0) + 0.05

    if _matches(COMPARISON_PATTERNS, text):
        deltas["jealousy"] = deltas.get("jealousy", 0) + 0.45
        deltas["joy"] = deltas.get("joy", 0) - 0.15
        deltas["respect_felt"] = deltas.get("respect_felt", 0) - 0.1

    return deltas
