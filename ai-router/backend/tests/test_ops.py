"""Hosted-scale control plane: kill switch, budget, breaker, rate limit,
observability, autonomy levels + approvals, model registry, data policy,
memory bounds, capacity planner and the admin API."""
import json
import os

import pytest
from fastapi.testclient import TestClient

import api
import learned
from control import Controls
from control.breaker import CircuitBreaker
from control.budget import BudgetGuard
from control.killswitch import KillSwitch
from control.ratelimit import SlidingWindowLimiter
from emotion.engine import EmotionEngine
from learned import chat_learning as cl
from learned import provenance
from learned.registry import ModelRegistry, gate
from ops import capacity
from router import AIRouter
from safety.autonomy import ApprovalQueue, level_for
from safety.permissions import ApprovalRequired, AuditLog, PermissionDenied, PermissionGuard
from utils.errors import AllProvidersFailedError, ProviderUnavailableError

NAMES = ["claude", "gemini", "zai", "groq", "cohere"]
USER = [{"role": "user", "content": "tell me something about the weather lol"}]


class Ok:
    def __init__(self, name="x"):
        self.name, self.calls = name, 0

    def chat(self, messages, **kw):
        self.calls += 1
        return f"reply from {self.name}"


class Down(Ok):
    def chat(self, messages, **kw):
        self.calls += 1
        raise ProviderUnavailableError("down")


class Boom(Ok):
    def chat(self, messages, **kw):
        self.calls += 1
        raise ValueError("bug in provider")


def make_router(tmp_path, providers=None, **ctl):
    controls = Controls.fresh(str(tmp_path), persist=False, **ctl)
    providers = providers or {n: Ok(n) for n in NAMES}
    return AIRouter(providers=providers, controls=controls), controls, providers


@pytest.fixture(autouse=True)
def no_chat_learning(monkeypatch):
    # keep these router tests from feeding the shared chat-learning store
    monkeypatch.setattr(learned, "record_fallback", lambda *a, **k: None)


# ── kill switch ────────────────────────────────────────────────────────────
def test_killswitch_persists_and_env_forces_off(tmp_path, monkeypatch):
    p = str(tmp_path / "ks.json")
    ks = KillSwitch(p)
    assert ks.learning_allowed() and ks.actions_allowed()
    ks.set(learning=False, reason="incident 12", by="admin1")
    again = KillSwitch(p)
    assert not again.learning_allowed() and again.actions_allowed()
    assert again.status()["reason"] == "incident 12"
    monkeypatch.setenv("KILL_SWITCH_ACTIONS", "1")
    forced = KillSwitch(str(tmp_path / "other.json"))
    forced.set(actions=True)                       # the API cannot switch it back on
    assert not forced.actions_allowed() and forced.status()["forced_by_env"]["actions"]


def test_killswitch_stops_chat_learning(tmp_path, monkeypatch):
    import control
    monkeypatch.setattr(cl, "STORE_PATH", str(tmp_path / "chat.json"))
    monkeypatch.setattr(cl, "ENABLED", True)
    monkeypatch.undo  # (fixture above already replaced learned.record_fallback)
    c = Controls.fresh(str(tmp_path))
    control.set_controls(c)
    try:
        q, a = "what is the capital of France", "Paris is the capital and largest city of France, on the Seine."
        assert cl.record(q, a, "claude", "s1") == "recorded"
        c.killswitch.set(learning=False)
        assert cl.record(q, a, "claude", "s2") == "skipped"
        assert cl.entries_for_training() == []
    finally:
        control.set_controls(None)


# ── budget ─────────────────────────────────────────────────────────────────
def test_call_cap_skips_provider_and_falls_back(tmp_path):
    router, ctl, prov = make_router(tmp_path, calls_cap=2)
    for _ in range(2):
        assert router.chat(USER, intent="casual")["provider"] == "claude"
    res = router.chat(USER, intent="casual")        # claude is capped -> groq
    assert res["provider"] == "groq"
    assert any("budget" in why for _, why in res["attempts"])


def test_budget_never_retries_a_capped_provider(tmp_path):
    router, ctl, prov = make_router(tmp_path, calls_cap=1)
    ctl.budget.record("claude"), ctl.budget.record("groq")
    with pytest.raises(AllProvidersFailedError):
        router.chat(USER, intent="casual")
    assert prov["claude"].calls == 0 and prov["groq"].calls == 0


def test_usd_cap_and_day_rollover(tmp_path):
    now = [1_700_000_000.0]
    b = BudgetGuard(path=str(tmp_path / "b.json"), usd_cap=1.0, prices={"claude": (10.0, 10.0)}, calls_cap=0,
                    clock=lambda: now[0])
    assert b.check("claude")[0]
    b.record("claude", in_chars=200_000, out_chars=200_000)     # 100k tokens * $10/M = $1.00
    assert b.snapshot()["estimated_usd_total"] == pytest.approx(1.0)
    assert not b.check("claude")[0] and not b.check("groq")[0]  # cap is global across providers
    now[0] += 86_400
    assert b.check("claude")[0]                                  # new UTC day, fresh budget


def test_budget_survives_restart(tmp_path):
    p = str(tmp_path / "b.json")
    b = BudgetGuard(path=p, calls_cap=3, usd_cap=0, prices={}, clock=lambda: 5_000_000_000.0)
    for _ in range(3):
        b.record("groq")
    b._last_persist = 0
    b.record("groq")                                             # forces a persist
    again = BudgetGuard(path=p, calls_cap=3, usd_cap=0, prices={}, clock=lambda: 5_000_000_000.0)
    assert not again.check("groq")[0]


# ── circuit breaker ────────────────────────────────────────────────────────
def test_breaker_opens_probes_and_recovers():
    t = [0.0]
    b = CircuitBreaker(failure_threshold=2, cooldown_s=10, clock=lambda: t[0])
    b.failure("groq"), b.failure("groq")
    assert b.state("groq") == "open" and not b.allow("groq")
    t[0] = 11
    assert b.allow("groq") and not b.allow("groq")       # exactly one probe
    b.failure("groq")                                    # probe failed -> open again
    assert b.state("groq") == "open"
    t[0] = 25
    assert b.allow("groq")
    b.success("groq")
    assert b.state("groq") == "closed" and b.allow("groq")


def test_router_skips_open_provider(tmp_path):
    prov = {n: Ok(n) for n in NAMES}
    prov["claude"] = Down("claude")
    router, ctl, _ = make_router(tmp_path, prov, breaker_failures=2, breaker_cooldown=60)
    for _ in range(2):
        assert router.chat(USER, intent="casual")["provider"] == "groq"
    assert prov["claude"].calls == 2
    res = router.chat(USER, intent="casual")
    assert prov["claude"].calls == 2                      # not called: circuit open
    assert ("claude", "circuit open") in res["attempts"]


def test_router_last_resort_when_every_circuit_is_open(tmp_path):
    router, ctl, prov = make_router(tmp_path, breaker_failures=1, breaker_cooldown=999)
    ctl.breaker.failure("claude"), ctl.breaker.failure("groq")
    assert router.chat(USER, intent="casual")["provider"] in ("claude", "groq")


def test_unexpected_provider_exception_falls_through(tmp_path):
    prov = {n: Ok(n) for n in NAMES}
    prov["claude"] = Boom("claude")
    router, ctl, _ = make_router(tmp_path, prov)
    res = router.chat(USER, intent="casual")
    assert res["provider"] == "groq" and res["attempts"][0][0] == "claude"


# ── rate limiting + validation ─────────────────────────────────────────────
def test_sliding_window_limiter():
    t = [0.0]
    lim = SlidingWindowLimiter(2, 60, clock=lambda: t[0])
    assert lim.hit("a")[0] and lim.hit("a")[0]
    ok, wait = lim.hit("a")
    assert not ok and 1 <= wait <= 61 and lim.hit("b")[0]
    t[0] = 61
    assert lim.hit("a")[0]
    assert SlidingWindowLimiter(0).hit("a") == (True, 0)  # 0 = off


def test_api_rate_limit_returns_429_with_retry_after(monkeypatch):
    class F:
        def chat(self, m, **k):
            return "ok"
    api.router.providers = {n: F() for n in NAMES}
    monkeypatch.setattr(api, "controls", Controls.fresh(os.environ["OPS_DATA_DIR"], persist=False, session_limit=2))
    c = TestClient(api.app)
    body = {"messages": [{"role": "user", "content": "tell me a joke lol"}], "session_id": "rl-test"}
    assert c.post("/chat", json=body).status_code == 200
    assert c.post("/chat", json=body).status_code == 200
    r = c.post("/chat", json=body)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_api_rejects_oversized_or_empty_chat(monkeypatch):
    c = TestClient(api.app)
    big = {"messages": [{"role": "user", "content": "x" * 200_000}], "session_id": "v1"}
    assert c.post("/chat", json=big).status_code == 413
    assert c.post("/chat", json={"messages": [], "session_id": "v2"}).status_code == 422


# ── observability ──────────────────────────────────────────────────────────
def test_decision_records_hold_no_text_and_hash_the_session(tmp_path):
    router, ctl, _ = make_router(tmp_path)
    router.chat([{"role": "user", "content": "my secret plan is ABC123 lol"}], intent="casual", session_id="alice-session")
    rec = ctl.observability.recent(1)[0]
    blob = json.dumps(rec)
    assert "ABC123" not in blob and "alice-session" not in blob
    assert rec["provider"] == "claude" and rec["ok"] and rec["latency_ms"] >= 0 and len(rec["session"]) == 8


def test_failures_are_recorded_and_raise_alert(tmp_path):
    prov = {n: Down(n) for n in NAMES}
    router, ctl, _ = make_router(tmp_path, prov, breaker_failures=0)
    for _ in range(25):
        with pytest.raises(AllProvidersFailedError):
            router.chat(USER, intent="casual")
    s = ctl.observability.summary()
    assert s["totals"]["failed"] == 25 and s["recent_error_rate"] == 1.0
    assert any(a["code"] == "error_rate" for a in ctl.alerts())


# ── autonomy levels, approvals, audit ──────────────────────────────────────
def guard(tmp_path, **kw):
    return PermissionGuard(audit_log=AuditLog(str(tmp_path / "audit.jsonl")),
                           approvals=ApprovalQueue(str(tmp_path / "ap.json")), **kw)


def test_levels():
    assert level_for("get_weather") == 0 and level_for("save_note") == 2
    assert level_for("send_message") == 3 and level_for("disable_logging") == 4


def test_level3_needs_grant_confirmation_and_a_human_approved_single_use_ticket(tmp_path):
    g = guard(tmp_path)
    ran = []
    g.grant("s1", "send_message")
    with pytest.raises(PermissionDenied):                       # no user confirmation
        g.execute("s1", "send_message", lambda: ran.append(1))
    with pytest.raises(ApprovalRequired) as e:                  # confirmed, but no ticket yet
        g.execute("s1", "send_message", lambda: ran.append(1), user_confirmed=True)
    ticket = e.value.approval_id
    with pytest.raises(ApprovalRequired):                       # still pending
        g.execute("s1", "send_message", lambda: ran.append(1), user_confirmed=True, approval_id=ticket)
    assert not ran
    g.approvals.decide(ticket, True, "admin")
    g.execute("s1", "send_message", lambda: ran.append(1), user_confirmed=True, approval_id=ticket)
    assert ran == [1]
    with pytest.raises(ApprovalRequired):                       # a ticket works once
        g.execute("s1", "send_message", lambda: ran.append(1), user_confirmed=True, approval_id=ticket)
    assert ran == [1]


def test_ticket_is_bound_to_session_and_action(tmp_path):
    g = guard(tmp_path)
    t = g.approvals.request("s1", "send_message")
    g.approvals.decide(t, True, "admin")
    assert not g.approvals.consume(t, "other-session", "send_message")
    assert not g.approvals.consume(t, "s1", "delete_data")
    assert g.approvals.consume(t, "s1", "send_message")


def test_rejected_and_expired_tickets_do_not_work(tmp_path):
    now = [1000.0]
    q = ApprovalQueue(str(tmp_path / "q.json"), ttl_s=60, clock=lambda: now[0])
    r = q.request("s", "send_message")
    q.decide(r, False, "admin")
    assert not q.consume(r, "s", "send_message")
    a = q.request("s", "delete_data")
    q.decide(a, True, "admin")
    now[0] += 61
    assert not q.consume(a, "s", "delete_data")


def test_kill_switch_blocks_actions_but_allows_reads(tmp_path):
    ks = KillSwitch(str(tmp_path / "ks.json"))
    g = guard(tmp_path, killswitch=ks)
    g.grant("s", "get_weather"), g.grant("s", "save_note")
    ks.set(actions=False)
    assert g.execute("s", "get_weather", lambda: "sunny") == "sunny"
    with pytest.raises(PermissionDenied):
        g.execute("s", "save_note", lambda: "x")
    ks.set(actions=True)
    assert g.execute("s", "save_note", lambda: "saved") == "saved"


def test_ceiling_and_never_permitted(tmp_path):
    g = guard(tmp_path, max_level=2)
    g.grant("s", "send_message")
    with pytest.raises(PermissionDenied):
        g.execute("s", "send_message", lambda: 1, user_confirmed=True)
    with pytest.raises(PermissionDenied):
        g.grant("s", "live_self_modification")
    with pytest.raises(PermissionDenied):
        g.execute("s", "disable_logging", lambda: 1)


def test_audit_log_is_persisted(tmp_path):
    g = guard(tmp_path)
    with pytest.raises(PermissionDenied):
        g.execute("s", "save_note", lambda: 1)
    lines = [json.loads(l) for l in open(tmp_path / "audit.jsonl")]
    assert lines[-1]["action"] == "save_note" and lines[-1]["allowed"] is False


# ── learned model registry, gate, sleep cycle, rollback ────────────────────
@pytest.fixture
def isolated_learned(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "STORE_PATH", str(tmp_path / "chat.json"))
    monkeypatch.setattr(learned, "ARTIFACT", str(tmp_path / "model.json"))
    monkeypatch.setitem(learned._state, "model", None)
    monkeypatch.setitem(learned._state, "meta", None)
    monkeypatch.setitem(learned._state, "last_gate", None)
    return tmp_path


def meta(wrong=0, ood=0, cov=0.8, val_ood=0):
    return {"test": {"answered_wrongly": wrong, "ood_wrongly_answered": ood, "coverage": cov},
            "validation_before_final_fit": {"ood_wrongly_answered": val_ood}, "n_entries": 4}


def test_gate_rules():
    assert gate(meta(), None).ok
    assert not gate(meta(wrong=1), None).ok
    assert not gate(meta(ood=1), None).ok
    assert not gate(meta(val_ood=1), None).ok
    assert not gate(meta(cov=0.5), meta(cov=0.8)).ok          # lost too much coverage
    assert gate(meta(cov=0.78), meta(cov=0.8)).ok             # within tolerance


def test_registry_promote_rollback_and_pin(tmp_path):
    reg = ModelRegistry(str(tmp_path / "reg"))
    a = reg.promote({"meta": meta(), "model": {"v": 1}})
    b = reg.promote({"meta": meta(), "model": {"v": 2}})
    assert reg.promote({"meta": meta(), "model": {"v": 2}}) == b      # identical model: no new version
    s = reg.summary()
    assert s["current"] == b and s["previous"] == a and not s["pinned"]
    blob = reg.rollback("admin")
    assert blob["model"] == {"v": 1} and reg.summary()["current"] == a and reg.is_pinned()
    reg.set_pinned(False)
    assert not reg.is_pinned()
    assert ModelRegistry(str(tmp_path / "empty")).rollback() is None


def test_sleep_cycle_promotes_a_passing_candidate_and_keeps_serving(isolated_learned):
    first = learned.sleep_cycle(by="test")
    assert first["ran"] and first["gate"]["promoted"]
    assert learned.answer_if_confident("what is a decision tree")["reply"]
    reg = learned._registry().summary()
    assert reg["current"] and os.path.exists(learned.ARTIFACT)


def test_sleep_cycle_discards_a_candidate_that_fails_the_gate(isolated_learned, monkeypatch):
    learned.sleep_cycle(by="test")
    live = learned._registry().summary()["current"]
    real = learned.train_and_save

    def bad(path, chat_entries=None):
        r = real(path, chat_entries=chat_entries)
        blob = json.load(open(path))
        blob["meta"]["test"]["answered_wrongly"] = 3          # a regression
        json.dump(blob, open(path, "w"))
        return r

    monkeypatch.setattr(learned, "train_and_save", bad)
    res = learned.sleep_cycle(by="test")
    assert res["gate"]["promoted"] is False and res["gate"]["ok"] is False
    assert learned._registry().summary()["current"] == live
    assert not os.path.exists(learned.ARTIFACT + ".candidate")
    assert learned.answer_if_confident("what is a decision tree")["reply"]   # still answering


def test_rollback_pins_and_blocks_sleep_until_unpinned(isolated_learned, monkeypatch):
    learned.sleep_cycle(by="test")
    # make a second, different version so there is something to roll back to
    reg = learned._registry()
    blob = json.load(open(learned.ARTIFACT))
    blob["model"]["threshold"] = round(blob["model"]["threshold"] + 0.001, 3)
    reg.promote(blob)
    assert reg.summary()["previous"]
    assert learned.rollback("admin") is not None and reg.is_pinned()
    res = learned.sleep_cycle(by="test")
    assert res["ran"] is False and "pinned" in res["reason"]
    learned.unpin("admin")
    assert learned.sleep_cycle(by="test")["ran"]


def test_kill_switch_stops_sleep_cycle(isolated_learned, monkeypatch):
    import control
    c = Controls.fresh(str(isolated_learned))
    c.killswitch.set(learning=False)
    control.set_controls(c)
    try:
        assert learned.sleep_cycle()["ran"] is False
    finally:
        control.set_controls(None)


# ── data provenance + independence policy ──────────────────────────────────
def test_provenance_register_labels_ai_generated_data(isolated_learned):
    reg = provenance.register()
    kinds = {d["id"]: d["kind"] for d in reg["datasets"]}
    assert kinds == {"curated_topics": "human_written", "out_of_domain_eval": "human_written", "chat_learned": "ai_generated"}
    assert all(d["licence"] for d in reg["datasets"])


def test_ai_data_policy_quarantine_and_exclude(isolated_learned, monkeypatch):
    monkeypatch.setattr(cl, "ENABLED", True)
    monkeypatch.setattr(cl, "MIN_ASKS", 1)
    q, a = "what is the capital of France", "Paris is the capital and largest city of France, on the Seine."
    monkeypatch.setattr(cl, "AI_DATA_POLICY", "quarantine")
    assert cl.record(q, a, "claude", "s1") in ("recorded", "ready")
    assert cl.entries_for_training() == []                     # on record, never trained on
    assert cl.provenance_counts()["by_provider"] == {"claude": 1}
    monkeypatch.setattr(cl, "AI_DATA_POLICY", "exclude")
    assert cl.record("why is the sky blue?", "Air scatters blue light more strongly than red light.", "groq", "s2") == "skipped"
    assert cl.provenance_counts()["total"] == 1


# ── memory bounds ──────────────────────────────────────────────────────────
def test_emotion_sessions_are_bounded_and_expire():
    t = [0.0]
    e = EmotionEngine(max_sessions=3, ttl_s=100, clock=lambda: t[0])
    for i in range(5):
        e.process_turn(f"s{i}", "hello")
    assert list(e.sessions) == ["s2", "s3", "s4"]              # least recently used evicted
    t[0] = 500
    e.process_turn("fresh", "hello")
    assert list(e.sessions) == ["fresh"]                       # idle sessions forgotten


# ── capacity planner (matches the table in the architecture document) ─────
@pytest.mark.parametrize("params,hours,low,high,train_gb,serve_gb", [
    (1e8, 0.8, 2, 4, 1.6, 0.2),
    (1e9, 84.3, 169, 379, 16.0, 2.0),
    (7e9, 4128.7, 8257, 18579, 112.0, 14.0),
    (3e10, 75834.2, 151668, 341254, 480.0, 60.0),
])
def test_capacity_matches_the_documented_table(params, hours, low, high, train_gb, serve_gb):
    p = capacity.plan_language_model(params)
    assert p["gpu_hours"] == pytest.approx(hours, rel=0.01)
    assert p["cost_usd"]["low"] == pytest.approx(low, rel=0.02, abs=1)
    assert p["cost_usd"]["high"] == pytest.approx(high, rel=0.02, abs=1)
    assert p["training_state_gb"] == train_gb and p["serving_memory_gb"] == serve_gb
    assert p["tokens"] == 20 * params


def test_capacity_spiking_memory():
    assert capacity.spiking_memory(1e5, 1e3)["memory_gb"] == pytest.approx(0.8)
    assert capacity.spiking_memory(1e7, 1e3)["memory_gb"] == pytest.approx(80)
    assert not capacity.spiking_memory(1e8, 1e3)["fits_one_h100"]
    assert capacity.training_memory_gb(1e9) == 16 and capacity.serving_memory_gb(1e9, 8) == 1


# ── admin API ──────────────────────────────────────────────────────────────
@pytest.fixture
def admin(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "controls", Controls.fresh(str(tmp_path), persist=False))
    monkeypatch.setattr(api, "audit_log", AuditLog(str(tmp_path / "audit.jsonl")))
    monkeypatch.setattr(api, "approvals", ApprovalQueue(str(tmp_path / "ap.json")))
    api.app.dependency_overrides[api.require_admin] = lambda: "admin-1"
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_admin_endpoints_refuse_non_admins():
    c = TestClient(api.app)
    for path in ("/admin/ops/status", "/admin/ops/decisions", "/admin/ops/provenance", "/admin/ops/audit"):
        assert c.get(path).status_code == 401                  # no bearer token at all
    assert c.post("/admin/ops/killswitch", json={"learning": False}).status_code == 401


def test_admin_status_killswitch_and_audit(admin):
    s = admin.get("/admin/ops/status").json()
    assert {"killswitch", "budget", "providers_circuit", "metrics", "alerts", "learned", "approvals_pending"} <= set(s)
    r = admin.post("/admin/ops/killswitch", json={"learning": False, "reason": "drill"}).json()
    assert r["learning_enabled"] is False and r["actions_enabled"] is True
    alerts = admin.get("/admin/ops/status").json()["alerts"]
    assert any(a["code"] == "kill_switch" for a in alerts)
    audit = admin.get("/admin/ops/audit").json()["entries"]
    assert audit[0]["action"] == "kill_switch" and audit[0]["session"] == "admin:admin-1"


def test_admin_approval_flow(admin):
    t = api.approvals.request("sess", "send_message", "send an email")
    assert admin.get("/admin/ops/status").json()["approvals_pending"][0]["id"] == t
    assert admin.post(f"/admin/ops/approvals/{t}/maybe").status_code == 400
    assert admin.post(f"/admin/ops/approvals/{t}/approve").json()["status"] == "approved"
    assert admin.post(f"/admin/ops/approvals/{t}/approve").status_code == 404   # already decided


def test_admin_capacity_and_provenance(admin):
    r = admin.get("/admin/ops/capacity", params={"params": 1e9}).json()
    assert r["plan"]["gpu_hours"] == pytest.approx(84.3, rel=0.01) and len(r["ladder"]) == 8
    assert admin.get("/admin/ops/capacity", params={"params": 5}).status_code == 400
    assert admin.get("/admin/ops/provenance").json()["datasets"]