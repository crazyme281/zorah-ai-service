"""Sliding-window rate limiter (in-process). Keys are things like an IP or a
session id; each key may make `limit` hits per `window_s` seconds."""
import threading
import time
from collections import deque


class SlidingWindowLimiter:
    MAX_KEYS = 20_000

    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self.rejected = 0

    def hit(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). limit <= 0 disables it."""
        if self.limit <= 0:
            return True, 0
        now = self.clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window_s
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                self.rejected += 1
                return False, max(1, int(q[0] + self.window_s - now) + 1)
            q.append(now)
            if len(self._hits) > self.MAX_KEYS:
                self._prune(cutoff)
            return True, 0

    def _prune(self, cutoff: float):
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]

    def stats(self) -> dict:
        return {"limit": self.limit, "window_s": self.window_s, "tracked_keys": len(self._hits),
                "rejected_total": self.rejected}