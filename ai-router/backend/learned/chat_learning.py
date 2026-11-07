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
from collections import Counter
from .text import features
from . import supabase_store as remote

HERE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.getenv("LEARNED_CHAT_STORE", os.path.join(HERE, "artifacts", "chat_learned.json"))
ENABLED = os.getenv("LEARN_FROM_CHAT", "1") != "0"
MIN_ASKS = int(os.getenv("LEARN_MIN_ASKS", "1"))   # vetted answers are kept after the first ask
RETRAIN_INTERVAL_S = int(os.getenv("LEARN_RETRAIN_INTERVAL_S", "60"))
SAME_QUESTION = 0.6      # unigram Jaccard for "this is the same question"
# Independence policy for text written by other AI models (all of it is):
#   allow      - learn from it (default, the behaviour the app shipped with)
#   quarantine - keep it on record but never train on it
#   exclude    - never store it
AI_DATA_POLICY = os.getenv("LEARN_AI_DATA_POLICY", "allow").strip().lower()
MAX_ENTRIES = 500
MAX_QUESTIONS = 8

_lock = threading.RLock()

_Q_START = re.compile(r"^(what|whats|how|why|when|where|who|which|is|are|can|could|does|do|did|define|explain|meaning of)\b", re.I)
_TASK = re.compile(r"\b(write|build|fix|debug|generate|create|translate|draft|summari[sz]e|rewrite|code|script|make me|compose|calculate|solve)\b", re.I)
_TIME = re.compile(r"\b(today|tonight|now|current|currently|latest|recent|recently|news|weather|price|prices|score|stock|tomorrow|yesterday|this (week|month|year)|right now|20\d\d)\b", re.I)
_SELF = re.compile(r"\b(my|mine|myself|our|ours)\b|\bi\s*(am|have|had|got)\b|\bi'?m\b|\bi'?ve\b", re.I)
_SENSITIVE = re.compile(r"password|passcode|\botp\b|\bpin\b|account number|card|\bssn\b|\bbvn\b|\bnin\b|salary|address|diagnos|prescri|symptom", re.I)
_PII = re.compile(r"@|https?://|www\.|\d{5,}|\+\d")
_CONTEXT = re.compile(r"\b(it|its|this|that|these|those|they|them|their|he|she|his|her|him|above|previous|earlier|again|the same|more about)\b", re.I)
_BAD_ANSWER = re.compile(r"as an ai|i don'?t know|i'?m not sure|i cannot|i can'?t|sorry|apolog|as of my|knowledge cutoff|you seem|you'?re feeling|i feel|real-?time|browse|search the web", re.I)


_last = {"note": "nothing yet", "at": 0}


def _note(text: str) -> None:
    """Remember the outcome of the latest attempt (no question text) so an
    admin can see why a question was or was not learned."""
    _last["note"], _last["at"] = text, int(time.time())


def _learning_allowed() -> bool:
    """False while the operator's kill switch has autonomous learning off."""
    try:
        from control import get_controls
        return get_controls().killswitch.learning_allowed()
    except Exception:
        return True


def provenance_counts() -> dict:
    """Counts only (never questions or answers), for the provenance register."""
    with _lock:
        entries = _load()["entries"]
    return {"total": len(entries),
            "by_status": dict(Counter(e["status"] for e in entries)),
            "by_provider": dict(Counter(e.get("provider", "unknown") for e in entries))}


def question_problem(q: str) -> str | None:
    """Why a question can't be learned, or None if it can."""
    q = (q or "").strip()
    if not (6 <= len(q) <= 150) or "\n" in q or "```" in q:
        return "question is too short, too long or has code"
    if not (_Q_START.match(q) or q.endswith("?")):
        return "not phrased as a question"
    if _TASK.search(q):
        return "asks for a task (write, fix, build...), not a fact"
    if _TIME.search(q):
        return "time-sensitive (today, latest, price...)"
    if _SELF.search(q) or _SENSITIVE.search(q) or _PII.search(q):
        return "personal or sensitive wording"
    if _CONTEXT.search(q):
        return "depends on earlier messages (it, this, that...)"
    return None


def answer_problem(a: str) -> str | None:
    a = (a or "").strip()
    if not (30 <= len(a) <= 1500):
        return "provider answer is too short or too long"
    if "```" in a or _PII.search(a):
        return "answer has code, a link or personal data"
    if _BAD_ANSWER.search(a):
        return "answer hedges or apologises"
    return None


def is_learnable_question(q: str) -> bool:
    return question_problem(q) is None


def is_learnable_answer(a: str) -> bool:
    return answer_problem(a) is None


def _sig(q: str) -> frozenset:
    return frozenset(f for f in features(q) if "_" not in f)


def _similar(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _session_hash(session_id) -> str:
    return hashlib.sha256(str(session_id or uuid.uuid4()).encode()).hexdigest()[:10]


_remote = {"pusher": remote.Pusher(), "cache": None, "path": None}


def _read_file() -> dict:
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"entries": []}


def _write_file(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
        tmp = STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)  # atomic
    except OSError:
        pass  # the Supabase copy (or the in-memory one) is still good


def _load() -> dict:
    """Entries live in Supabase when it is configured (read once, then served
    from memory); otherwise in the local JSON file."""
    if not remote.enabled():
        return _read_file()
    if _remote["cache"] is not None and _remote["path"] == STORE_PATH:
        return _remote["cache"]
    local = _read_file()
    stored = remote.fetch_all()
    if stored is None:  # Supabase unreachable: keep working from the file, try again next time
        return local
    merged = {e["id"]: e for e in local["entries"]}
    merged.update({e["id"]: e for e in stored})   # Supabase wins
    data = {"entries": list(merged.values())}
    _remote["pusher"].mark_remote(stored)
    _remote["cache"], _remote["path"] = data, STORE_PATH
    _remote["pusher"].push(data["entries"])       # first run: upload what only the file had
    return data


def _save(data: dict) -> None:
    _write_file(data)
    if remote.enabled():
        _remote["cache"], _remote["path"] = data, STORE_PATH
        _remote["pusher"].push(data["entries"])


def record(question: str, answer: str, provider: str, session_id=None) -> str:
    """Remember a provider answer. Returns 'skipped', 'recorded' or 'ready'."""
    if not ENABLED or AI_DATA_POLICY == "exclude" or not _learning_allowed():
        _note("skipped: learning is switched off")
        return "skipped"
    problem = question_problem(question) or answer_problem(answer)
    if problem:
        _note(f"skipped: {problem}")
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
                     "provider": provider, "source": "provider_generated", "sessions": [],
                     "status": "pending", "first_seen": now}
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
        _note("saved: queued for training" if ready else "saved: already known, waiting")
        return "ready" if ready else "recorded"


def entries_for_training() -> list[dict]:
    """Entries asked in enough sessions; never rejected ones."""
    if AI_DATA_POLICY in ("quarantine", "exclude") or not _learning_allowed():
        return []
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
        return {"enabled": ENABLED, "min_asks": MIN_ASKS, "ai_data_policy": AI_DATA_POLICY,
                "storage": "supabase" if remote.enabled() else "file",
                "last_attempt": dict(_last), **c}