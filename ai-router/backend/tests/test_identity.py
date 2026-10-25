import pytest
from identity import (DISPLAY_NAME, is_identity_question, identity_reply,
                      IDENTITY_SYSTEM_PROMPT)
from identity import asks_about_company, asks_about_technology, asks_about_creator_bio, CREATOR, CREATOR_BIO
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


def test_plain_identity_answer_is_confident_and_short():
    r = identity_reply("What AI model are you using?")
    assert r.startswith(f"I'm {DISPLAY_NAME}, the AI assistant in Zorah.")
    for hedge in ["isn't", "not the name", "reliable", "don't have", "underlying"]:
        assert hedge not in r
    for provider in ["OpenAI", "Anthropic", "Google", "Gemini", "Claude", "Groq", "Cohere"]:
        assert provider not in r


@pytest.mark.parametrize("q", ["Who made you?", "who built you", "Which company is behind you?",
                               "who is your creator"])
def test_company_questions_get_a_confident_answer_naming_zorah(q):
    assert is_identity_question(q) and asks_about_company(q) and not asks_about_technology(q)
    r = identity_reply(q)
    assert r.startswith(f"I'm {DISPLAY_NAME}, built by Zorah.")
    assert CREATOR in r and "don't have" not in r
    assert "Qplus" not in r and "cloud computing" not in r   # full background only when asked about him


@pytest.mark.parametrize("q", ["Are you ChatGPT?", "are you claude", "what is your underlying model",
                               "which provider powers you", "who trained you"])
def test_technology_questions_stay_honest_without_inventing(q):
    assert is_identity_question(q) and asks_about_technology(q)
    r = identity_reply(q)
    assert r.startswith(f"I'm {DISPLAY_NAME}, built by Zorah.") and "don't have details" in r
    for provider in ["OpenAI", "Anthropic", "Google", "Gemini", "Claude", "Groq", "Cohere"]:
        assert provider not in r
    assert not r.lower().startswith("no")  # never deny being a model it might be built on


def test_plain_questions_are_neither_company_nor_technology_questions():
    assert not asks_about_technology("What AI model are you using?")
    assert not asks_about_company("What AI model are you using?")


def test_public_label_and_scrub_never_carry_the_name():
    assert DISPLAY_NAME not in public_model_label()
    out = scrub_result_for_user({"reply": "x", "provider": "claude", "intent": "i",
                                 "attempts": [], "model_label": "claude-internal"})
    assert DISPLAY_NAME not in out["model_label"] and "provider" not in out


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

def test_system_prompt_only_allows_the_name_when_asked():
    p = IDENTITY_SYSTEM_PROMPT
    assert p.startswith("Only if the user asks")
    assert "never mention the name" in p and "never introduce yourself" in p


def test_normal_chat_responses_never_contain_the_name():
    from fastapi.testclient import TestClient
    import api

    class F:
        def chat(self, m, **k):
            return "Here is a normal answer about recursion."

    api.router.providers = {n: F() for n in ["claude", "gemini", "zai", "groq", "cohere"]}
    c = TestClient(api.app)
    for text in ("hello", "Explain recursion", "write a poem"):
        body = {"messages": [{"role": "user", "content": text}], "session_id": "n1"}
        assert DISPLAY_NAME not in c.post("/chat", json=body).text
        assert DISPLAY_NAME not in c.post("/chat/stream", json=body).text
    asked = c.post("/chat", json={"messages": [{"role": "user", "content": "Which model is this?"}], "session_id": "n2"}).json()
    assert DISPLAY_NAME in asked["reply"] and DISPLAY_NAME not in asked["model_label"]


@pytest.mark.parametrize("q", ["Who is Ubom Delight Emmanuel?", "tell me about ubom", "who is ubom",
                               "Tell me about your creator", "tell me about your developer", "who is Delight Emmanuel"])
def test_questions_about_the_creator_get_the_full_background(q):
    assert is_identity_question(q) and asks_about_creator_bio(q)
    r = identity_reply(q)
    assert r == CREATOR_BIO
    for fact in ["Ubom Delight Emmanuel", "software developer", "Qplus GNL", "Bytehub Cafe",
                 "Swavy Global", "cloud computing at 18", "studying computer science"]:
        assert fact in r


@pytest.mark.parametrize("q", ["who is ubom samuel", "tell me about the developer of react",
                               "who is the owner of this restaurant", "about ubuntu", "tell me about the developer",
                               "who is the creator of Python"])
def test_other_people_and_topics_are_not_intercepted(q):
    assert not asks_about_creator_bio(q)
    assert not is_identity_question(q)


def test_background_never_appears_in_normal_answers():
    assert "Ubom" not in identity_reply("What AI model are you using?")
    assert "Ubom" not in identity_reply("are you claude")