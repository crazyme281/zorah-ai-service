"""
Central configuration for the multi-provider AI router.

Everything that changes often (which model a provider uses, which
provider handles which task, timeouts) lives here so the routing
logic in router.py never has to change when you swap a model.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# API keys — pulled once, validated at startup so failures happen at boot
# instead of mid-conversation.
# ---------------------------------------------------------------------------
API_KEYS = {
    "claude": os.getenv("CLAUDE_API_KEY"),
    "gemini": os.getenv("GEMINI_API_KEY"),
    "zai": os.getenv("ZAI_API_KEY"),
    "cohere": os.getenv("COHERE_API_KEY"),
    "groq": os.getenv("GROQ_API_KEY"),
}


def missing_keys() -> list[str]:
    return [name for name, key in API_KEYS.items() if not key]


# ---------------------------------------------------------------------------
# Server-side-only credentials for subscriptions/quota (Supabase) and
# payment verification (Flutterwave). These must NEVER reach the
# frontend — the service-role key in particular bypasses every RLS
# policy in the database.
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")


# ---------------------------------------------------------------------------
# Which model each provider should use. Keeping this separate from the key
# means bumping a model version is a one-line change.
# ---------------------------------------------------------------------------
MODELS = {
    "claude": "claude-haiku-4-5-20251001",
    # gemini-2.0-flash was retired; Google's deprecation error names this
    # as its replacement. If this breaks in turn later, whatever error
    # Gemini returns will again name the model to switch to.
    "gemini": "gemini-3.6-flash",
    "zai": "glm-4-plus",
    "groq": "openai/gpt-oss-120b",
    "cohere_chat": "command-r-plus",
    "cohere_embed": "embed-english-v3.0",
    "cohere_rerank": "rerank-english-v3.0",
}


# ---------------------------------------------------------------------------
# Routing table. Each intent maps to a primary provider and an ordered
# list of fallbacks tried in sequence if the primary errors out or is
# rate-limited. "rag" is shaped differently since it's a two-stage
# retrieve-then-generate pipeline, not a single chat call.
# ---------------------------------------------------------------------------
@dataclass
class Route:
    primary: str
    fallbacks: list[str] = field(default_factory=list)


ROUTES: dict[str, Route] = {
    "greeting": Route(primary="claude", fallbacks=["groq"]),
    "casual": Route(primary="claude", fallbacks=["groq"]),
    "education": Route(primary="gemini", fallbacks=["groq"]),
    "large_document": Route(primary="gemini", fallbacks=[]),
    "coding": Route(primary="zai", fallbacks=["groq"]),
    "agent": Route(primary="zai", fallbacks=["claude", "groq"]),
    "fast": Route(primary="groq", fallbacks=["claude"]),
    # fallback used when the classifier genuinely can't decide
    "default": Route(primary="groq", fallbacks=["claude"]),
}

RAG_ROUTE = {
    "retrieval": "cohere",
    "generation": "gemini",
    "generation_fallback": "groq",
}

# Per-call timeout in seconds. A provider that hangs past this is treated
# as failed and the router moves to the next fallback.
REQUEST_TIMEOUT = 30