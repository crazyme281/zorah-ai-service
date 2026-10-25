"""
Learning from the chat page.

When the learned model is NOT sure, a normal provider answers. This module may
remember that question + answer so next time the learned model can answer it
itself. It is a cache of vetted provider answers, not training of the provider.

Safeguards (all tested):
  * only standalone factual questions (single user turn, no image, no code);
  * nothing personal, time-sensitive or task-like; no emails/numbers/URLs;
  * the answer must look like a clean, self-contained answer;
  * a question must be asked in >= LEARN_MIN_ASKS different sessions;
  * sessions are stored only as short one-way hashes; no user ids, no raw text
    beyond the question/answer pair itself;
  * promotion to the live model is gated by a held-out safety check (train.py).
Switch off with LEARN_FROM_CHAT=0.
"""
import hashlib, json, os, re, threading, time, uuid
from .text import features

HERE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.getenv("LEARNED_CHAT_STORE", os.path.join(HERE, "artifacts", "chat_learned.json"))
ENABLED = os.getenv("LEARN_FROM_CHAT", "1") != "0"
MIN_ASKS = int(os.getenv("LEARN_MIN_ASKS", "2"))
RETRAIN_INTERVAL_S = int(os.getenv("LEARN_RETRAIN_INTERVAL_S", "600"))
SAME_QUESTION = 0.6      # unigram Jaccard for "this is the same question"
MAX_ENTRIES = 500
MAX_QUESTIONS = 8

_lock = threading.RLock()

_Q_START = re.compile(r"^(what|whats|how|why|when|where|who|which|is|are|can|could|does|do|did|define|explain|meaning of)\b", re.I)
_TASK = re.compile(r"\b(write|build|fix|debug|generate|create|translate|draft|summari[sz]e|rewrite|code|script|make me|compose|calculate|solve)\b", re.I)
_TIME = re.compile(r"\b(today|tonight|now|current|currently|latest|recent|recently|news|weather|price|prices|score|stock|tomorrow|yesterday|this (week|month|year)|right now|20\d\d)\b", re.I)
_SELF = re.compile(r"\b(my|mine|myself|our|ours)\b|\bi\s*(am|have|had|got)\b|\bi'?m\b|\bi'?ve\b", re.I)
_SENSITIVE = re.compile(r"password|passcode|\botp\b|\bpin\b|account number|card|\bssn\b|\bbvn\b|\bnin\b|salary|address|diagnos|prescri|symptom", re.I)
_PII = re.compile(r"@|https?://|www\.|\d{5,}|\+\d")
_BAD_ANSWER = re.compile(r"as an ai|i don'?t know|i'?m not sure|i cannot|i can'?t|sorry|apolog|as of my|knowledge cutoff|you seem|you'?re feeling|i feel|real-?time|browse|search the web", re.I)


def is_learnable_question(q: str) -> bool:
    q = (q or "").strip()
    if not (6 <= len(q) <= 150) or "\n" in q or "```" in q:
        return False
    if not (_Q_START.match(q) or q.endswith("?")):
        return False
    return not (_TASK.search(q) or _TIME.search(q) or _SELF.search(q) or _SENSITIVE.search(q) or _PII.search(q))


def is_learnable_answer(a: str) -> bool:
    a = (a or "").strip()
    return 30 <= len(a) <= 1500 and "```" not in a and not _PII.search(a) and not _BAD_ANSWER.search(a)


def _sig(q: str) -> frozenset:
    return frozenset(f for f in features(q) if "_" not in f)


def _similar(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _session_hash(session_id) -> str:
    return hashlib.sha256(str(session_id or uuid.uuid4()).encode()).hexdigest()[:10]


def _load() -> dict:
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"entries": []}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, STORE_PATH)  # atomic


def record(question: str, answer: str, provider: str, session_id=None) -> str:
    """Remember a provider answer. Returns 'skipped', 'recorded' or 'ready'."""
    if not ENABLED or not is_learnable_question(question) or not is_learnable_answer(answer):
        return "skipped"
    sig, sh = _sig(question), _session_hash(session_id)
    with _lock:
        data = _load()
        entries = data["entries"]
        match = next((e for e in entries if _similar(sig, _sig(e["questions"][0])) >= SAME_QUESTION), None)
        now = int(time.time())
        if match is None:
            if len(entries) >= MAX_ENTRIES:
                return "skipped"
            match = {"id": "chat_" + uuid.uuid4().hex[:8], "questions": [question.strip()], "answer": answer.strip(),
                     "provider": provider, "sessions": [], "status": "pending", "first_seen": now}
            entries.append(match)
        elif question.strip().lower() not in (x.lower() for x in match["questions"]) and len(match["questions"]) < MAX_QUESTIONS:
            match["questions"].append(question.strip())
        if sh not in match["sessions"]:
            match["sessions"] = (match["sessions"] + [sh])[-20:]
        match["last_seen"] = now
        ready = match["status"] == "pending" and len(match["sessions"]) >= MIN_ASKS
        if ready:
            match["status"] = "queued"
        _save(data)
        return "ready" if ready else "recorded"


def entries_for_training() -> list[dict]:
    """Entries asked in enough sessions; never rejected ones."""
    with _lock:
        return [e for e in _load()["entries"]
                if e["status"] in ("queued", "active") and len(e["sessions"]) >= MIN_ASKS]


def mark(used_ids: set, rejected: dict) -> None:
    """After a training run: queued -> active (used) or rejected (+reason)."""
    with _lock:
        data = _load()
        for e in data["entries"]:
            if e["id"] in used_ids:
                e["status"] = "active"
            elif e["id"] in rejected:
                e["status"], e["reason"] = "rejected", rejected[e["id"]]
        _save(data)


def summary() -> dict:
    """Counts only. Never exposes users' questions or answers."""
    with _lock:
        c = {"pending": 0, "queued": 0, "active": 0, "rejected": 0}
        for e in _load()["entries"]:
            c[e["status"]] = c.get(e["status"], 0) + 1
        return {"enabled": ENABLED, "min_asks": MIN_ASKS, **c}