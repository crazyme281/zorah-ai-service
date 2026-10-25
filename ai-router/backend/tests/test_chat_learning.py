import json
import pytest
import learned
from learned import chat_learning as cl
from learned.train import train_and_save
from router import AIRouter

GOOD = "Paris is the capital and largest city of France, located on the river Seine."


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "STORE_PATH", str(tmp_path / "chat.json"))
    monkeypatch.setattr(cl, "ENABLED", True)
    monkeypatch.setattr(cl, "MIN_ASKS", 2)
    monkeypatch.setattr(learned, "ARTIFACT", str(tmp_path / "model.json"))
    monkeypatch.setitem(learned._state, "model", None)
    monkeypatch.setitem(learned._state, "meta", None)
    learned.train_and_save(str(tmp_path / "model.json"))     # baseline artifact for this test
    yield


class Fake:
    def __init__(self, reply=GOOD):
        self.reply, self.calls = reply, 0

    def chat(self, messages, **kw):
        self.calls += 1
        return self.reply


def make_router(reply=GOOD):
    fakes = {n: Fake(reply) for n in ["claude", "gemini", "zai", "groq", "cohere"]}
    return AIRouter(providers=fakes), fakes


def ask(router, q, session):
    return router.chat([{"role": "user", "content": q}], session_id=session)


def calls(fakes):
    return sum(f.calls for f in fakes.values())


@pytest.mark.parametrize("q", [
    "what is the capital of France", "how does photosynthesis work", "why is the sky blue?",
    "define entropy in physics"])
def test_learnable_questions(q):
    assert cl.is_learnable_question(q)


@pytest.mark.parametrize("q", [
    "what is my bank balance", "what's the weather today", "write a poem about the sea",
    "what is the latest iphone", "who won in 2026", "how do I reset my password",
    "what is 4155550123 about", "email me at a@b.com what is x", "fix this bug", "hello",
    "what is this?\nsecond line", "how is I'm learning french going"])
def test_unlearnable_questions(q):
    assert not cl.is_learnable_question(q)


@pytest.mark.parametrize("a", ["Sorry, I can't help.", "I don't know the answer to that one really.",
                               "As of my knowledge cutoff the answer was this and that.", "short",
                               "See https://example.com for details about the answer.", "```code``` " * 5])
def test_unlearnable_answers(a):
    assert not cl.is_learnable_answer(a)


def test_needs_two_different_sessions():
    assert cl.record("what is the capital of France", GOOD, "claude", "s1") == "recorded"
    assert cl.record("what is the capital of France", GOOD, "claude", "s1") == "recorded"  # same session
    assert cl.record("capital of France?", GOOD, "claude", "s2") == "ready"                # paraphrase, new session
    data = json.load(open(cl.STORE_PATH))
    assert len(data["entries"]) == 1 and len(data["entries"][0]["questions"]) == 2
    assert "s1" not in json.dumps(data)                                                   # only hashes stored


def test_end_to_end_learns_from_chat_then_answers_without_providers():
    router, fakes = make_router()
    assert ask(router, "what is the capital of France", "a")["provider"] != "learned"
    assert ask(router, "what is the capital of France", "b")["provider"] != "learned"
    report = learned.retrain_now()
    assert report["chat_learning"]["gate"] == "passed" and report["chat_learning"]["used"] == 1
    before = calls(fakes)
    res = ask(router, "what is the capital of France", "c")
    assert res["provider"] == "learned" and res["reply"] == GOOD
    assert calls(fakes) == before                      # no other model was called
    assert learned.model_info()["chat_learning"]["active"] == 1


def test_unsure_questions_still_use_other_models_after_learning():
    router, fakes = make_router()
    for s in "ab":
        ask(router, "what is the capital of France", s)
    learned.retrain_now()
    before = calls(fakes)
    assert ask(router, "what is the capital of Spain city name", "z")["provider"] != "learned"
    assert calls(fakes) == before + 1


def test_safety_gate_rejects_knowledge_that_would_break_held_out_tests():
    bad = [{"id": "chat_bad", "questions": ["write a poem about the ocean"], "answer": "x" * 40}]
    report = train_and_save(cl.STORE_PATH + ".m", chat_entries=bad)
    assert report["chat_learning"]["used"] == 0 and "chat_bad" in report["_rejected"]
    assert report["test"]["ood_wrongly_answered"] == 0


def test_chat_entries_need_extra_confidence():
    router, fakes = make_router()
    for s in "ab":
        ask(router, "what is the capital of France", s)
    learned.retrain_now()
    learned._state["model"].chat_margin = 0.99
    assert ask(router, "what is the capital of France", "c")["provider"] != "learned"


def test_not_recorded_for_followups_images_or_when_disabled(monkeypatch):
    router, _ = make_router()
    two_turns = [{"role": "user", "content": "hi there"}, {"role": "assistant", "content": "hello"},
                 {"role": "user", "content": "what is the capital of France"}]
    router.chat(two_turns, session_id="x")
    img = [{"role": "user", "content": [{"type": "text", "text": "what is the capital of France"},
                                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    router.chat(img, session_id="y")
    monkeypatch.setattr(cl, "ENABLED", False)
    ask(router, "what is the capital of France", "z")
    assert not json.load(open(cl.STORE_PATH))["entries"] if __import__("os").path.exists(cl.STORE_PATH) else True


def test_summary_never_exposes_questions():
    cl.record("what is the capital of France", GOOD, "claude", "s1")
    s = json.dumps(learned.model_info()["chat_learning"])
    assert "France" not in s and "pending" in s


def test_recording_failure_never_breaks_chat(monkeypatch):
    monkeypatch.setattr(cl, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    router, _ = make_router()
    assert ask(router, "what is the capital of France", "a")["reply"] == GOOD