"""
Decision records and metrics.

One record per chat turn: which route was taken, who answered, how long it
took, how many providers were tried, the learned model's confidence. Records
NEVER contain message text or user ids - the session is stored as a short
one-way hash - so they are safe to keep and to show an admin.
"""
import hashlib
import os
import threading
import time
from collections import Counter, deque

from config import DATA_DIR
from control.store import append_jsonl


def _pct(sorted_vals: list, q: float):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


class Observability:
    def __init__(self, path: str | None = None, ring: int = 500, persist: bool = True):
        self.path = path or os.path.join(DATA_DIR, "decisions.jsonl")
        self.persist = persist
        self._ring: deque = deque(maxlen=ring)
        self._lock = threading.Lock()
        self.started_at = int(time.time())
        self.totals = Counter()

    def record(self, *, intent, provider, ok, latency_ms, attempts=0, failed=(), confidence=None,
               persona=False, has_image=False, in_chars=0, out_chars=0, session_id=None):
        rec = {
            "ts": int(time.time()), "intent": intent, "provider": provider, "ok": bool(ok),
            "latency_ms": int(latency_ms), "attempts": int(attempts), "failed": list(failed),
            "confidence": confidence, "persona": bool(persona), "has_image": bool(has_image),
            "in_chars": int(in_chars), "out_chars": int(out_chars),
            "session": hashlib.sha256(str(session_id).encode()).hexdigest()[:8] if session_id else None,
        }
        with self._lock:
            self._ring.append(rec)
            self.totals["requests"] += 1
            self.totals["ok" if ok else "failed"] += 1
        if self.persist:
            append_jsonl(self.path, rec)
        return rec

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._ring)[-max(1, min(n, 500)):][::-1]

    def summary(self) -> dict:
        with self._lock:
            recs = list(self._ring)
            totals = dict(self.totals)
        per: dict[str, dict] = {}
        for r in recs:
            p = per.setdefault(r["provider"] or "none", {"calls": 0, "errors": 0, "lat": []})
            p["calls"] += 1
            p["errors"] += 0 if r["ok"] else 1
            if r["ok"]:
                p["lat"].append(r["latency_ms"])
        providers = {}
        for name, p in per.items():
            lat = sorted(p["lat"])
            providers[name] = {"calls": p["calls"], "errors": p["errors"],
                               "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)}
        last50 = recs[-50:]
        learned = [r for r in recs if r["provider"] == "learned"]
        return {
            "since": self.started_at,
            "totals": totals,
            "window": len(recs),
            "recent_error_rate": round(sum(1 for r in last50 if not r["ok"]) / len(last50), 3) if last50 else 0.0,
            "learned_share": round(len(learned) / len(recs), 3) if recs else 0.0,
            "providers": providers,
            "intents": dict(Counter(r["intent"] for r in recs)),
        }