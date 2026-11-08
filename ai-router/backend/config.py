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
    # Only used by Code Fixer's own provider chain (access/codefix_ai.py),
    # not the main chat router — OpenAI isn't part of ROUTES below.
    "openai": os.getenv("OPENAI_API_KEY"),
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
    # Code Fixer only — a cost-effective default; override with the
    # OPENAI_MODEL env var if you want a stronger (and pricier) model
    # for this specifically.
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
}


# ---------------------------------------------------------------------------
# Code Fixer — the separate worker service that actually runs untrusted
# `npm install`/`pytest`/etc. It holds no secrets of its own; the main
# backend authenticates to it with this shared secret and nothing else.
def _clean_worker_url(raw: str | None) -> str | None:
    """Forgive the usual typos: spaces, a missing https://, a trailing slash,
    or a pasted /run or /health on the end."""
    url = (raw or "").strip().strip("\"'")
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    url = url.rstrip("/")
    for suffix in ("/run", "/health"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    return url


WORKER_URL = _clean_worker_url(os.getenv("CODE_FIXER_WORKER_URL"))
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET")

MAX_UPLOAD_ZIP_BYTES = 60 * 1024 * 1024
MAX_EXTRACTED_BYTES = 300 * 1024 * 1024
MAX_UPLOAD_FILE_COUNT = 6000
MAX_REPAIR_ATTEMPTS = 3
# Total characters of source handed to the AI in one call — keeps the
# request bounded regardless of how large the uploaded project is.
CODE_CONTEXT_BUDGET_CHARS = 60_000


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
REQUEST_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Hosted-scale operations (see control/, safety/autonomy.py, learned/registry.py)
#
# Everything here is read once at boot from environment variables so the
# limits can be changed in the Render dashboard without a code change.
# A value of 0 means "off / unlimited" unless stated otherwise.
# ---------------------------------------------------------------------------
def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Where small operational state lives (kill switch, budget counters, audit
# log, decision records, approval queue). On Render, point this at a
# persistent disk (e.g. /var/data) or it is wiped on every deploy.
DATA_DIR = os.getenv("OPS_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Abuse and overload: sliding-window request limits on the public chat API.
RATE_LIMIT_IP_PER_MIN = _int("RATE_LIMIT_IP_PER_MIN", 60)
RATE_LIMIT_SESSION_PER_MIN = _int("RATE_LIMIT_SESSION_PER_MIN", 20)
MAX_CHAT_MESSAGES = _int("MAX_CHAT_MESSAGES", 200)
MAX_CHAT_TEXT_CHARS = _int("MAX_CHAT_TEXT_CHARS", 120_000)  # text only; image data is not counted

# Runaway spending: hard daily caps. Calls are counted per provider; dollars
# need the per-million-token prices below (PRICE_<PROVIDER>_IN_PER_M and
# PRICE_<PROVIDER>_OUT_PER_M, e.g. PRICE_CLAUDE_IN_PER_M=1.0) - prices are
# never guessed, so with no prices set only the call caps can bite.
BUDGET_DAILY_CALLS_PER_PROVIDER = _int("BUDGET_DAILY_CALLS_PER_PROVIDER", 0)
BUDGET_DAILY_USD = _float("BUDGET_DAILY_USD", 0.0)
BUDGET_ALERT_FRACTION = _float("BUDGET_ALERT_FRACTION", 0.8)

# Resilience: a provider failing this many times in a row is skipped for the
# cool-down, then probed with a single request.
BREAKER_FAILURES = _int("BREAKER_FAILURES", 5)
BREAKER_COOLDOWN_S = _int("BREAKER_COOLDOWN_S", 30)

# Autonomy: highest level an action may have and still run (3 = needs a
# human-approved ticket, 4 = never). Lower it to 2 to forbid external effects.
AUTONOMY_MAX_LEVEL = _int("AUTONOMY_MAX_LEVEL", 3)
APPROVAL_TTL_S = _int("APPROVAL_TTL_S", 24 * 3600)

# Memory: emotional working-memory is per session and lives in RAM, so it is
# bounded to keep an always-on service from growing without limit.
EMOTION_MAX_SESSIONS = _int("EMOTION_MAX_SESSIONS", 5000)
EMOTION_SESSION_TTL_S = _int("EMOTION_SESSION_TTL_S", 6 * 3600)

# Sleep / consolidation of the learned model: 0 = only when an admin runs it
# (or when enough chat questions are queued).
SLEEP_INTERVAL_S = _int("SLEEP_INTERVAL_S", 0)