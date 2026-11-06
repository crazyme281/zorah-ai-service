"""
The control plane: everything that keeps an always-on, hosted service safe,
affordable and observable. One shared `Controls` bundle is used by the router
and the API; tests build their own with `Controls.fresh(tmp_dir)`.
"""
import os
from dataclasses import dataclass

from config import (BREAKER_COOLDOWN_S, BREAKER_FAILURES, RATE_LIMIT_IP_PER_MIN,
                    RATE_LIMIT_SESSION_PER_MIN)
from control.breaker import CircuitBreaker
from control.budget import BudgetGuard
from control.killswitch import KillSwitch
from control.observability import Observability
from control.ratelimit import SlidingWindowLimiter


@dataclass
class Controls:
    killswitch: KillSwitch
    budget: BudgetGuard
    breaker: CircuitBreaker
    observability: Observability
    ip_limiter: SlidingWindowLimiter
    session_limiter: SlidingWindowLimiter

    @classmethod
    def fresh(cls, data_dir: str, persist: bool = True, **overrides) -> "Controls":
        return cls(
            killswitch=KillSwitch(os.path.join(data_dir, "killswitch.json")),
            budget=BudgetGuard(path=os.path.join(data_dir, "budget.json"),
                               **{k: v for k, v in overrides.items() if k in ("calls_cap", "usd_cap", "prices")}),
            breaker=CircuitBreaker(overrides.get("breaker_failures", BREAKER_FAILURES),
                                   overrides.get("breaker_cooldown", BREAKER_COOLDOWN_S)),
            observability=Observability(os.path.join(data_dir, "decisions.jsonl"), persist=persist),
            ip_limiter=SlidingWindowLimiter(overrides.get("ip_limit", RATE_LIMIT_IP_PER_MIN)),
            session_limiter=SlidingWindowLimiter(overrides.get("session_limit", RATE_LIMIT_SESSION_PER_MIN)),
        )

    def alerts(self) -> list[dict]:
        """Things an operator should look at right now."""
        out = []
        ks = self.killswitch.status()
        if not ks["learning_enabled"] or not ks["actions_enabled"]:
            off = [n for n, on in (("learning", ks["learning_enabled"]), ("actions", ks["actions_enabled"])) if not on]
            out.append({"level": "warn", "code": "kill_switch", "message": f"Kill switch is off for: {', '.join(off)}"})
        for name, b in self.breaker.snapshot().items():
            if b["state"] != "closed":
                out.append({"level": "error", "code": "provider_circuit",
                            "message": f"{name} is {b['state']} after repeated failures ({b['last_error'] or 'no detail'})"})
        if self.budget.snapshot()["near_cap"]:
            out.append({"level": "warn", "code": "budget", "message": "Daily budget is above its alert threshold"})
        s = self.observability.summary()
        if s["window"] >= 20 and s["recent_error_rate"] >= 0.5:
            out.append({"level": "error", "code": "error_rate",
                        "message": f"{int(s['recent_error_rate'] * 100)}% of the last requests failed"})
        return out

    def snapshot(self) -> dict:
        return {
            "killswitch": self.killswitch.status(),
            "budget": self.budget.snapshot(),
            "providers_circuit": self.breaker.snapshot(),
            "metrics": self.observability.summary(),
            "rate_limits": {"ip": self.ip_limiter.stats(), "session": self.session_limiter.stats()},
            "alerts": self.alerts(),
        }


_shared: Controls | None = None


def get_controls() -> Controls:
    """The process-wide bundle, created on first use."""
    global _shared
    if _shared is None:
        from config import DATA_DIR
        _shared = Controls.fresh(DATA_DIR)
    return _shared


def set_controls(c: Controls | None) -> None:
    """Swap the shared bundle (tests)."""
    global _shared
    _shared = c