"""
Confidence-gated learned answers.

answer_if_confident(text) returns a dict when the learned model is sure, and
None when it is not, in which case the router uses the other models.

Training never changes the live model directly. A "sleep cycle" trains a
CANDIDATE, runs it through the regression gate (registry.gate), and only a
passing candidate is promoted - the previous version is kept for rollback.
The operator's kill switch stops the whole cycle (see control/killswitch.py).
"""
import json, logging, os, threading, time
from .model import LearnedModel
from .train import ARTIFACT, CONTENT, content_hash, train_and_save
from . import chat_learning
from .registry import ModelRegistry, gate

logger = logging.getLogger("ai_router.learned")
MAX_CHARS = 200
_lock = threading.Lock()
_state = {"model": None, "meta": None, "last_gate": None}
STATS = {"asked": 0, "answered_by_learned": 0, "fell_back": 0, "last_confidence": None, "last_retrain": 0}


def _registry() -> ModelRegistry:
    # Resolved on every call so it always sits next to the live artifact.
    return ModelRegistry(os.path.join(os.path.dirname(ARTIFACT), "registry"))


def _learning_allowed() -> bool:
    try:
        from control import get_controls
        return get_controls().killswitch.learning_allowed()
    except Exception:
        return True


def _install(blob: dict):
    _state["model"] = LearnedModel.from_dict(blob["model"])
    _state["meta"] = blob["meta"]


def _load():
    with _lock:
        if _state["model"] is not None:
            return _state["model"]
        reg = _registry()
        if reg.is_pinned():  # an operator rolled back: keep exactly that version
            blob = reg.load_current()
            if blob:
                _install(blob)
                return _state["model"]
        meta = None
        if os.path.exists(ARTIFACT):
            try:
                blob = json.load(open(ARTIFACT))
                if blob["meta"].get("content_hash") == content_hash():
                    _state["model"], meta = LearnedModel.from_dict(blob["model"]), blob["meta"]
            except Exception:  # corrupt artifact -> retrain below
                logger.warning("learned artifact unreadable; retraining", exc_info=True)
        if _state["model"] is None:
            meta = _train()  # content changed or no artifact yet
        _state["meta"] = meta
        return _state["model"]


def _train(by: str = "sleep") -> dict:
    """Train a candidate, gate it, promote it only if it passes. Returns the
    meta of whichever model is live afterwards. Caller holds no lock."""
    reg = _registry()
    bootstrap = _state["model"] is None
    if reg.is_pinned() and not bootstrap:
        _state["last_gate"] = {"promoted": False, "ok": None, "reasons": ["a rolled-back version is pinned"], "at": int(time.time())}
        return _state["meta"]

    candidate = ARTIFACT + ".candidate"
    report = train_and_save(candidate, chat_entries=chat_learning.entries_for_training())
    used, rejected = report.pop("_used_ids", set()), report.pop("_rejected", {})
    blob = json.load(open(candidate))
    verdict = gate(blob["meta"], None if bootstrap else _state["meta"])

    if verdict.ok or bootstrap:
        if not verdict.ok:
            logger.warning("learned: first model failed the gate (%s) but nothing else is live", verdict.reasons)
        os.replace(candidate, ARTIFACT)
        reg.promote(blob, verdict, by=by)
        _install(blob)
        chat_learning.mark(used, rejected)
        _state["last_gate"] = {"promoted": True, "ok": verdict.ok, "reasons": verdict.reasons, "at": int(time.time())}
    else:
        logger.warning("learned: candidate rejected by the gate: %s", verdict.reasons)
        try:
            os.remove(candidate)
        except OSError:
            pass
        reg.reject(blob["meta"], verdict, by=by)
        _state["last_gate"] = {"promoted": False, "ok": False, "reasons": verdict.reasons, "at": int(time.time())}
    return _state["meta"]


def retrain_now() -> dict:
    with _lock:
        STATS["last_retrain"] = int(time.time())
        return _train()


def sleep_cycle(by: str = "sleep", force: bool = False) -> dict:
    """Consolidation: train a candidate from curated + vetted chat knowledge,
    run the gate, promote or discard. Stopped by the kill switch."""
    if not _learning_allowed():
        return {"ran": False, "reason": "kill switch: autonomous learning is off"}
    _load()
    if _registry().is_pinned() and not force:
        return {"ran": False, "reason": "a rolled-back version is pinned; unpin it first"}
    before = _registry().summary()["current"]
    with _lock:
        STATS["last_retrain"] = int(time.time())
        _train(by)
    after = _registry().summary()
    return {"ran": True, "version_before": before, "version_after": after["current"],
            "gate": _state["last_gate"]}


def rollback(by: str = "admin"):
    """Make the previous version live again (and pinned). None if there is none."""
    _load()
    with _lock:
        blob = _registry().rollback(by)
        if blob is None:
            return None
        with open(ARTIFACT, "w") as f:
            json.dump(blob, f)
        _install(blob)
        return _state["meta"]


def unpin(by: str = "admin") -> None:
    _registry().set_pinned(False, by)


_timer = {"t": None}


def _schedule_retrain():
    """At most one retrain per LEARN_RETRAIN_INTERVAL_S, off the request path."""
    with _lock:
        if _timer["t"] is not None:
            return
        wait = max(0, STATS["last_retrain"] + chat_learning.RETRAIN_INTERVAL_S - time.time()) if STATS["last_retrain"] else 0

        def run():
            try:
                if _learning_allowed():
                    retrain_now()
            except Exception:
                logger.exception("learned: background retrain failed")
            finally:
                _timer["t"] = None

        _timer["t"] = threading.Timer(wait, run)
        _timer["t"].daemon = True
        _timer["t"].start()


_sleeper = {"t": None}


def start_sleep_scheduler(interval_s: int) -> bool:
    """Run sleep_cycle() every interval_s seconds on a daemon thread. A free
    Render instance is spun down when idle, so this only matters on an
    always-on plan; admins can also trigger a cycle from the ops page."""
    if interval_s <= 0 or _sleeper["t"] is not None:
        return False

    def loop():
        while True:
            time.sleep(interval_s)
            try:
                sleep_cycle(by="scheduler")
            except Exception:
                logger.exception("learned: scheduled sleep cycle failed")

    _sleeper["t"] = threading.Thread(target=loop, daemon=True, name="learned-sleep")
    _sleeper["t"].start()
    return True


def record_fallback(question: str, answer: str, provider: str, session_id=None) -> None:
    """Called after another model answered. Never raises, never blocks chat."""
    try:
        if not _learning_allowed():
            return
        if chat_learning.record(question, answer, provider, session_id) == "ready":
            _schedule_retrain()
    except Exception:
        logger.exception("learned: could not record chat answer")


def answer_if_confident(text: str):
    if not text or len(text) > MAX_CHARS or "```" in text:
        return None
    model = _load()
    STATS["asked"] += 1
    entry, conf = model.predict(text)
    STATS["last_confidence"] = conf
    if entry is None:
        STATS["fell_back"] += 1
        logger.info("learned: not sure (conf=%.2f) -> other models", conf)
        return None
    STATS["answered_by_learned"] += 1
    logger.info("learned: answered %s (conf=%.2f)", entry, conf)
    return {"reply": model.answers[entry], "entry": entry, "confidence": conf}


def model_info() -> dict:
    _load()
    return {"meta": _state["meta"], "stats": dict(STATS), "chat_learning": chat_learning.summary()}


def admin_info() -> dict:
    """model_info plus the registry and last gate result (admin only)."""
    _load()
    return {**model_info(), "registry": _registry().summary(), "last_gate": _state["last_gate"]}