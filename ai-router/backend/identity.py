"""
Assistant identity: the user-facing name "lite1.2".

This is a DISPLAY name only. It is kept separate from the real provider and
model ids in config.py / router.py, which are untouched by anything here.
"""
import os
import re

DISPLAY_NAME = os.getenv("ASSISTANT_DISPLAY_NAME", "lite1.2")

IDENTITY_SYSTEM_PROMPT = (
    f"Your user-facing name is {DISPLAY_NAME}. If asked who or what you are, or "
    f"which AI model you use, say you are {DISPLAY_NAME}, the assistant in this "
    f"app. {DISPLAY_NAME} is the app's name for the assistant, not the name of the "
    "underlying model, provider or weights; never claim otherwise, and never "
    "state or guess a provider or model name."
)

_PATTERNS = [
    r"\bwhat\s+(?:ai\s+|llm\s+|language\s+)?model\b[^?\n]{0,25}\b(?:you|this)\b",
    r"\bwhich\s+(?:ai\s+|llm\s+|language\s+)?(?:model|version|ai|llm|bot|chatbot|assistant)\b[^?\n]{0,25}\b(?:you|this)\b",
    r"\bwhat(?:'s|\s+is)\s+your\s+(?:model|model\s+name|ai\s+model|version)\b",
    r"\bwho\s+(?:are\s+you|made\s+you|built\s+you|created\s+you)\b",
    r"\bwhat(?:'s|\s+is)\s+your\s+name\b",
    r"\bwhat\s+are\s+you\b(?!\s+(?:doing|going|talking|thinking|up))",
    r"\bwhat\s+(?:ai|llm|model)\s+are\s+you\b",
    r"\bare\s+you\s+(?:chatgpt|gpt|claude|gemini|llama|mistral|deepseek|copilot|glm|cohere)\b",
    r"\bwhich\s+(?:company|provider)\b[^?\n]{0,25}\b(?:you|model|this)\b",
]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def is_identity_question(text: str) -> bool:
    """True when the message asks the assistant about its own identity/model."""
    if not text or len(text) > 300:  # long messages are real tasks
        return False
    return any(rx.search(text) for rx in _RX)


def identity_reply() -> str:
    return (
        f"I'm {DISPLAY_NAME}, the AI assistant in this app. {DISPLAY_NAME} is the "
        "name this app gives me; it isn't the name of the underlying model or "
        "provider, and I don't have reliable details about which specific model "
        "handled this message."
    )