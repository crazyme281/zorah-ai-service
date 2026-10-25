"""
Assistant identity: the user-facing name "lite1.2", built by Zorah.

lite1.2 appears ONLY in answers to a user asking the assistant about itself.
It is a display name, kept separate from the real provider/model ids in
config.py / router.py, which nothing here touches.
"""
import os
import re

DISPLAY_NAME = os.getenv("ASSISTANT_DISPLAY_NAME", "lite1.2")
COMPANY = "Zorah"
CREATOR = "Ubom Delight Emmanuel"
# Full background is shared only when someone asks about him specifically.
CREATOR_BIO = (
    f"{CREATOR} is the software developer who created {COMPANY} and {DISPLAY_NAME}. "
    "He has worked with companies including Qplus GNL, Bytehub Cafe and Swavy Global. "
    "He completed his first degree in cloud computing at 18 and is now studying "
    "computer science."
)

IDENTITY_SYSTEM_PROMPT = (
    f"Only if the user asks which AI or model you are, or what your name is, answer "
    f"confidently and briefly: you are {DISPLAY_NAME}, the AI assistant in {COMPANY}. "
    f"If asked who made you or which company is behind you, say {COMPANY} built you and it was created by {CREATOR}, a software developer. "
    f"If asked about the underlying technology, provider or base model, say you don't "
    f"have details about that. Add no other disclaimers. Otherwise never mention the "
    f"name {DISPLAY_NAME} and never introduce yourself with it. Never state or guess a "
    f"provider or model name."
)

# Plain "which model / who are you" questions.
_GENERAL = [
    r"\bwhat\s+(?:ai\s+|llm\s+|language\s+)?model\b[^?\n]{0,25}\b(?:you|this)\b",
    r"\bwhich\s+(?:ai\s+|llm\s+|language\s+)?(?:model|version|ai|llm|bot|chatbot|assistant)\b[^?\n]{0,25}\b(?:you|this)\b",
    r"\bwhat(?:'s|\s+is)\s+your\s+(?:model|model\s+name|ai\s+model|version)\b",
    r"\bwho\s+are\s+you\b",
    r"\bwhat(?:'s|\s+is)\s+your\s+name\b",
    r"\bwhat\s+are\s+you\b(?!\s+(?:doing|going|talking|thinking|up))",
    r"\bwhat\s+(?:ai|llm|model)\s+are\s+you\b",
]
# Who is behind it: answered confidently, the company is Zorah.
_COMPANY = [
    r"\bwho\s+(?:made|built|created|developed|owns)\s+you\b",
    r"\bwho\s+(?:is|are)\s+your\s+(?:creator|maker|developer|owner)s?\b",
    r"\b(?:which|what)\s+company\b[^?\n]{0,25}\b(?:you|behind|made|built|owns?)\b",
]
# Asking about the creator as a person: gets the full background.
_BIO = [
    r"\bubom\s+(?:delight\s+)?emmanuel\b",
    r"\bdelight\s+emmanuel\b",
    r"\bubom\s+delight\b",
    r"^\W*(?:who\s+is|tell\s+me\s+about|about)\s+ubom\W*$",
    r"\b(?:tell\s+me\s+about|about)\s+your\s+(?:creator|developer|founder|owner|maker)\b",
]
# Underlying technology: answered without inventing details.
_TECH = [
    r"\bwho\s+trained\s+you\b",
    r"\bare\s+you\s+(?:chatgpt|gpt|claude|gemini|llama|mistral|deepseek|copilot|glm|cohere)\b",
    r"\b(?:which|what)\s+provider\b[^?\n]{0,25}\b(?:you|model|this)\b",
    r"\bwhat\s+technology\b[^?\n]{0,25}\b(?:you|behind|powers?)\b",
    r"\bwhat\s+powers\s+you\b",
    r"\b(?:underlying|base)\s+model\b",
]
_RX_GENERAL = [re.compile(p, re.IGNORECASE) for p in _GENERAL]
_RX_COMPANY = [re.compile(p, re.IGNORECASE) for p in _COMPANY]
_RX_TECH = [re.compile(p, re.IGNORECASE) for p in _TECH]
_RX_BIO = [re.compile(p, re.IGNORECASE) for p in _BIO]


def _short(text: str) -> bool:
    return bool(text) and len(text) <= 300  # long messages are real tasks


def asks_about_creator_bio(text: str) -> bool:
    return _short(text) and any(rx.search(text) for rx in _RX_BIO)


def asks_about_technology(text: str) -> bool:
    return _short(text) and any(rx.search(text) for rx in _RX_TECH)


def asks_about_company(text: str) -> bool:
    return (_short(text) and not asks_about_technology(text) and not asks_about_creator_bio(text)
            and any(rx.search(text) for rx in _RX_COMPANY))


def is_identity_question(text: str) -> bool:
    """True when the message asks the assistant about its own identity/model."""
    if not _short(text):
        return False
    return any(rx.search(text) for rx in _RX_GENERAL + _RX_COMPANY + _RX_TECH + _RX_BIO)


def identity_reply(question: str = "") -> str:
    if asks_about_creator_bio(question):
        return CREATOR_BIO
    if asks_about_technology(question):
        return (f"I'm {DISPLAY_NAME}, built by {COMPANY}. I don't have details about the "
                "underlying technology, but I'm happy to help with whatever you need.")
    if asks_about_company(question):
        return (f"I'm {DISPLAY_NAME}, built by {COMPANY}. {COMPANY} was created by {CREATOR}, a software "
                "developer. Ask me about him if you'd like to know more.")
    return f"I'm {DISPLAY_NAME}, the AI assistant in {COMPANY}. What can I help you with?"