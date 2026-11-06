"""
Per-provider circuit breaker. After `failure_threshold` failures in a row a
provider is skipped for `cooldown_s`; then exactly one probe request is let
through (half-open). A success closes the circuit, a failure re-opens it.
This stops a dead provider from costing every request its full timeout.
"""
import threading
import time

from config import BREAKER_COOLDOWN_S, BREAKER_FAILURES


class CircuitBreaker:
    def __init__(self, failure_threshold: int = BREAKER_FAILURES, cooldown_s: float = BREAKER_COOLDOWN_S,
                 clock=time.monotonic):
        self.threshold, self.cooldown, self.clock = failure_threshold, cooldown_s, clock
        self._s: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _get(self, name: str) -> dict:
        return self._s.setdefault(name, {"failures": 0, "opened_at": None, "probing": False,
                                         "last_error": "", "total_failures": 0, "trips": 0})

    def allow(self, name: str) -> bool:
        if self.threshold <= 0:
            return True
        with self._lock:
            s = self._get(name)
            if s["opened_at"] is None:
                return True
            if self.clock() - s["opened_at"] >= self.cooldown and not s["probing"]:
                s["probing"] = True  # half-open: one probe only
                return True
            return False

    def success(self, name: str):
        with self._lock:
            s = self._get(name)
            s.update(failures=0, opened_at=None, probing=False)

    def failure(self, name: str, error: str = ""):
        with self._lock:
            s = self._get(name)
            s["failures"] += 1
            s["total_failures"] += 1
            s["last_error"] = error[:160]
            was_open = s["opened_at"] is not None
            if self.threshold > 0 and (s["failures"] >= self.threshold or s["probing"]):
                if not was_open:
                    s["trips"] += 1
                s["opened_at"], s["probing"] = self.clock(), False

    def state(self, name: str) -> str:
        s = self._s.get(name)
        if not s or s["opened_at"] is None:
            return "closed"
        return "half-open" if self.clock() - s["opened_at"] >= self.cooldown else "open"

    def snapshot(self) -> dict:
        with self._lock:
            return {n: {"state": self.state(n), "consecutive_failures": s["failures"],
                        "total_failures": s["total_failures"], "trips": s["trips"],
                        "last_error": s["last_error"]} for n, s in self._s.items()}