import pytest
from identity import (DISPLAY_NAME, is_identity_question, identity_reply,
                      IDENTITY_SYSTEM_PROMPT)
from branding import public_model_label, scrub_result_for_user
from router import AIRouter
from config import ROUTES


class FakeProvider:
    def __init__(self, name):
        self.name, self.calls = name, []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return f"reply from {self.name}"


def make_router():
    fakes = {n: FakeProvider(n) for n in ["claude", "gemini", "zai", "groq", "cohere"]}
    return AIRouter(providers=fakes), fakes


@pytest.mark.parametrize("q", [
    "What AI model are you using?", "Which model is this?", "what model are you",
    "Who are you?", "what's your name", "Are you ChatGPT?", "What LLM are you?",
    "which AI is this?", "What is your model?"])
def test_identity_questions_detected(q):
    assert is_identity_question(q)


@pytest.mark.parametrize("q", [
    "What model of car should I buy?", "Explain decision trees", "what are you doing later",
    "Write a poem about models", "", "x " * 400 + "who are you"])
def test_normal_messages_not_intercepted(q):
    assert not is_identity_question(q)


def test_reply_is_honest():
    r = identity_reply()
    assert DISPLAY_NAME == "lite1.2" and DISPLAY_NAME in r
    assert "isn't the name of the underlying model" in r
    for provider in ["OpenAI", "Anthropic", "Google", "Gemini", "Claude", "Groq", "Cohere"]:
        assert provider not in r


def test_public_label_and_scrub():
    assert public_model_label() == "lite1.2"
    out = scrub_result_for_user({"reply": "x", "provider": "claude", "intent": "i",
                                 "attempts": [], "model_label": "claude-internal"})
    assert out["model_label"] == "lite1.2" and "provider" not in out


def test_router_answers_identity_without_calling_providers():
    router, fakes = make_router()
    res = router.chat([{"role": "user", "content": "What AI model are you using?"}])
    assert DISPLAY_NAME in res["reply"] and res["provider"] == "identity"
    assert all(not f.calls for f in fakes.values())


def test_router_injects_identity_prompt_but_keeps_history_unmutated():
    router, fakes = make_router()
    history = [{"role": "user", "content": "Explain recursion"}]
    res = router.chat(history)
    assert res["reply"].startswith("reply from")
    sent = next(f.calls for f in fakes.values() if f.calls)[0]
    assert sent[0]["role"] == "system" and IDENTITY_SYSTEM_PROMPT in sent[0]["content"]
    assert history == [{"role": "user", "content": "Explain recursion"}]  # stored history untouched


def test_identity_prompt_merges_with_persona_directive():
    router, fakes = make_router()
    msgs = [{"role": "system", "content": "PERSONA"}, {"role": "user", "content": "hi"}]
    router.chat(msgs)
    sent = next(f.calls for f in fakes.values() if f.calls)[0]
    assert sent[0]["content"].startswith("PERSONA") and DISPLAY_NAME in sent[0]["content"]
    assert sum(1 for m in sent if m["role"] == "system") == 1


def test_image_messages_still_go_to_a_provider():
    router, fakes = make_router()
    content = [{"type": "text", "text": "who are you"},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    res = router.chat([{"role": "user", "content": content}])
    assert res["provider"] != "identity"