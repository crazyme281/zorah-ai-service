"""
Confidence-gated learned answers.

answer_if_confident(text) returns a dict when the learned model is sure, and
None when it is not, in which case the router uses the other models.
"""
import json, logging, os, threading, time
from .model import LearnedModel
from .train import ARTIFACT, CONTENT, content_hash, train_and_save
from . import chat_learning

logger = logging.getLogger("ai_router.learned")
MAX_CHARS = 200
_lock = threading.Lock()
_state = {"model": None, "meta": None}
STATS = {"asked": 0, "answered_by_learned": 0, "fell_back": 0, "last_confidence": None, "last_retrain": 0}


def _load():
    with _lock:
        if _state["model"] is not None:
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


def _train() -> dict:
    """Train (curated + vetted chat knowledge) and swap the live model."""
    report = train_and_save(ARTIFACT, chat_entries=chat_learning.entries_for_training())
    chat_learning.mark(report.pop("_used_ids", set()), report.pop("_rejected", {}))
    blob = json.load(open(ARTIFACT))
    _state["model"] = LearnedModel.from_dict(blob["model"])
    _state["meta"] = blob["meta"]
    return blob["meta"]


def retrain_now() -> dict:
    with _lock:
        STATS["last_retrain"] = int(time.time())
        return _train()


_timer = {"t": None}


def _schedule_retrain():
    """At most one retrain per LEARN_RETRAIN_INTERVAL_S, off the request path."""
    with _lock:
        if _timer["t"] is not None:
            return
        wait = max(0, STATS["last_retrain"] + chat_learning.RETRAIN_INTERVAL_S - time.time()) if STATS["last_retrain"] else 0

        def run():
            try:
                retrain_now()
            except Exception:
                logger.exception("learned: background retrain failed")
            finally:
                _timer["t"] = None

        _timer["t"] = threading.Timer(wait, run)
        _timer["t"].daemon = True
        _timer["t"].start()


def record_fallback(question: str, answer: str, provider: str, session_id=None) -> None:
    """Called after another model answered. Never raises, never blocks chat."""
    try:
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