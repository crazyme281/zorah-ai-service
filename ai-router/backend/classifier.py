"""
Lightweight, dependency-free intent classifier.

Keyword/heuristic based on purpose: it's instant and free, which matters
because it runs on every single message before any paid API call. Swap
in a real classifier later (e.g. a Groq call with a tiny prompt) by
replacing classify() — everything downstream just consumes the string
it returns, so no other file needs to change.
"""
import re

GREETING_PATTERNS = re.compile(
    r"^\s*(hi|hello|hey|good\s*(morning|afternoon|evening)|yo|sup|what'?s up)\b",
    re.IGNORECASE,
)

CODING_KEYWORDS = [
    "code", "function", "bug", "error", "stack trace", "python", "javascript",
    "java ", "sql", "regex", "compile", "syntax", "refactor", "api endpoint",
    "class ", "def ", "algorithm", "debug", "traceback", "npm", "pip install",
]

EDUCATION_KEYWORDS = [
    "explain", "what is", "how does", "why does", "define", "homework",
    "assignment", "exam", "study", "lecture", "theorem", "concept", "history of",
    "chemistry", "physics", "biology", "mathematics", "essay",
]

RAG_KEYWORDS = [
    "according to the document", "in the pdf", "in the notes", "from the file",
    "search the database", "find in my documents", "based on the uploaded",
]

AGENT_KEYWORDS = [
    "call the", "use the tool", "execute", "run the workflow", "automate",
    "schedule a", "send an email", "book a", "trigger",
]

CASUAL_KEYWORDS = [
    "lol", "haha", "how are you", "what's your name", "tell me a joke",
    "chat with you", "bored",
]


def classify(message: str) -> str:
    text = message.strip().lower()

    if not text:
        return "default"

    if GREETING_PATTERNS.match(text) and len(text) < 40:
        return "greeting"

    if any(kw in text for kw in RAG_KEYWORDS):
        return "rag"

    if any(kw in text for kw in AGENT_KEYWORDS):
        return "agent"

    if any(kw in text for kw in CODING_KEYWORDS):
        return "coding"

    if any(kw in text for kw in EDUCATION_KEYWORDS):
        return "education"

    if any(kw in text for kw in CASUAL_KEYWORDS) or len(text) < 20:
        return "casual"

    # Long, information-dense message with no other signal — treat as
    # education/explanation rather than casual chat.
    if len(text) > 200:
        return "education"

    return "default"
