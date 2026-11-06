"""
Budget guard: hard daily caps so a bug, a loop or an abusive client cannot
run up a provider bill.

  * calls per provider per UTC day (BUDGET_DAILY_CALLS_PER_PROVIDER)
  * estimated dollars per UTC day across providers (BUDGET_DAILY_USD),
    which needs per-million-token prices in the environment - prices are
    never guessed here.

Tokens are estimated as characters / 4. Counters are saved to disk so a
restart does not hand back a fresh budget. A provider that is over its cap is
skipped by the router exactly like one that is down.
"""
import logging
import os
import threading
import time

from config import BUDGET_ALERT_FRACTION, BUDGET_DAILY_CALLS_PER_PROVIDER, BUDGET_DAILY_USD, DATA_DIR
from control.store import read_json, write_json

logger = logging.getLogger("ai_router.budget")
CHARS_PER_TOKEN = 4
PERSIST_EVERY_S = 2.0


def _prices_from_env(providers=("claude", "gemini", "zai", "groq", "cohere")) -> dict:
    out = {}
    for p in providers:
        try:
            i = float(os.getenv(f"PRICE_{p.upper()}_IN_PER_M", "0") or 0)
            o = float(os.getenv(f"PRICE_{p.upper()}_OUT_PER_M", "0") or 0)
        except ValueError:
            continue
        if i or o:
            out[p] = (i, o)
    return out


class BudgetGuard:
    def __init__(self, path=None, calls_cap=None, usd_cap=None, prices=None, clock=time.time):
        self.path = path or os.path.join(DATA_DIR, "budget.json")
        self.calls_cap = BUDGET_DAILY_CALLS_PER_PROVIDER if calls_cap is None else calls_cap
        self.usd_cap = BUDGET_DAILY_USD if usd_cap is None else usd_cap
        self.prices = _prices_from_env() if prices is None else prices
        self.clock = clock
        self._lock = threading.RLock()
        self._last_persist = 0.0
        self._alerted: set[str] = set()
        saved = read_json(self.path, {})
        self._day = saved.get("day") or self._today()
        self._providers: dict[str, dict] = saved.get("providers", {})

    # -- helpers ----------------------------------------------------------
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    def _roll(self):
        today = self._today()
        if today != self._day:
            self._day, self._providers, self._alerted = today, {}, set()

    def _cost(self, provider: str, in_chars: int, out_chars: int) -> float:
        i, o = self.prices.get(provider, (0.0, 0.0))
        return (in_chars / CHARS_PER_TOKEN) / 1e6 * i + (out_chars / CHARS_PER_TOKEN) / 1e6 * o

    def _total_usd(self) -> float:
        return sum(p.get("usd", 0.0) for p in self._providers.values())

    def _alert(self, key: str, message: str):
        if key not in self._alerted:
            self._alerted.add(key)
            logger.error("BUDGET ALERT: %s", message)

    # -- API --------------------------------------------------------------
    def check(self, provider: str) -> tuple[bool, str]:
        """(allowed, reason). Called before each provider attempt."""
        with self._lock:
            self._roll()
            calls = self._providers.get(provider, {}).get("calls", 0)
            if self.calls_cap and calls >= self.calls_cap:
                self._alert(f"calls:{provider}", f"{provider} reached its daily cap of {self.calls_cap} calls")
                return False, f"daily call cap reached ({self.calls_cap})"
            if self.usd_cap and self._total_usd() >= self.usd_cap:
                self._alert("usd", f"daily spend estimate reached ${self.usd_cap:.2f}")
                return False, f"daily spend cap reached (${self.usd_cap:.2f})"
            return True, ""

    def record(self, provider: str, in_chars: int = 0, out_chars: int = 0):
        with self._lock:
            self._roll()
            p = self._providers.setdefault(provider, {"calls": 0, "in_chars": 0, "out_chars": 0, "usd": 0.0})
            p["calls"] += 1
            p["in_chars"] += int(in_chars)
            p["out_chars"] += int(out_chars)
            p["usd"] = round(p["usd"] + self._cost(provider, in_chars, out_chars), 6)
            if self.calls_cap and p["calls"] >= BUDGET_ALERT_FRACTION * self.calls_cap:
                self._alert(f"calls80:{provider}", f"{provider} is at {p['calls']}/{self.calls_cap} daily calls")
            if self.usd_cap and self._total_usd() >= BUDGET_ALERT_FRACTION * self.usd_cap:
                self._alert("usd80", f"spend estimate ${self._total_usd():.2f} of ${self.usd_cap:.2f}")
            now = self.clock()
            if now - self._last_persist >= PERSIST_EVERY_S:
                self._last_persist = now
                write_json(self.path, {"day": self._day, "providers": self._providers})

    def snapshot(self) -> dict:
        with self._lock:
            self._roll()
            total = self._total_usd()
            return {
                "day": self._day,
                "calls_cap_per_provider": self.calls_cap or None,
                "usd_cap": self.usd_cap or None,
                "prices_configured": sorted(self.prices),
                "estimated_usd_total": round(total, 4),
                "providers": {k: dict(v) for k, v in self._providers.items()},
                "near_cap": bool(
                    (self.usd_cap and total >= BUDGET_ALERT_FRACTION * self.usd_cap)
                    or (self.calls_cap and any(v["calls"] >= BUDGET_ALERT_FRACTION * self.calls_cap
                                               for v in self._providers.values()))
                ),
            }