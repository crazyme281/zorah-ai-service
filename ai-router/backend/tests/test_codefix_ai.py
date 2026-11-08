"""Code Fixer's AI step: tolerate messy replies and fall back with clear errors."""
import json

import pytest

from access import codefix_ai as ai

GOOD = {"problems": ["syntax error"], "fixes": [{"path": "a.py", "new_content": "x=1\n", "reason": "fix"}]}


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text or json.dumps(body)

    def json(self):
        return self._body


def gemini_body(text, finish="STOP", thought=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


def claude_body(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(ai, "API_KEYS", {"gemini": "g", "claude": "c", "openai": "", "groq": "q"})


def route(monkeypatch, handlers):
    calls = []

    def post(url, **kw):
        for needle, fn in handlers.items():
            if needle in url:
                calls.append(needle)
                return fn() if callable(fn) else fn
        raise AssertionError(url)
    monkeypatch.setattr(ai.requests, "post", post)
    return calls


@pytest.mark.parametrize("raw", [
    json.dumps(GOOD),
    "```json\n" + json.dumps(GOOD) + "\n```",
    "Here is the fix:\n" + json.dumps(GOOD) + "\nHope it helps!",
    "```\n" + json.dumps(GOOD) + "\n```",
])
def test_parses_fenced_and_chatty_replies(raw):
    assert ai._parse_json_response(raw)["fixes"][0]["path"] == "a.py"


@pytest.mark.parametrize("raw,why", [("", "empty"), ("   ", "empty"), ("sorry I cannot", "not JSON"),
                                     ('{"fixes": [{"path": "a.py", "new_con', "cut off"), ('{"nothing": 1}', "fixes")])
def test_bad_replies_say_why(raw, why):
    with pytest.raises(ai._BadReply) as e:
        ai._parse_json_response(raw)
    assert why in str(e.value)


def test_empty_gemini_reply_is_retried_once_then_claude_answers(keys, monkeypatch):
    seq = iter([Resp(body=gemini_body("")), Resp(body=gemini_body(""))])
    calls = route(monkeypatch, {"googleapis": lambda: next(seq), "anthropic": Resp(body=claude_body(json.dumps(GOOD)))})
    assert ai.propose_fixes("ctx")["fixes"]
    assert calls == ["googleapis", "googleapis", "anthropic"]


def test_gemini_retry_succeeds_without_falling_back(keys, monkeypatch):
    seq = iter([Resp(body=gemini_body("")), Resp(body=gemini_body(json.dumps(GOOD)))])
    calls = route(monkeypatch, {"googleapis": lambda: next(seq)})
    assert ai.propose_fixes("ctx")["fixes"] and calls == ["googleapis", "googleapis"]


def test_thinking_parts_are_ignored(keys, monkeypatch):
    route(monkeypatch, {"googleapis": Resp(body=gemini_body(json.dumps(GOOD), thought="let me think..."))})
    assert ai.propose_fixes("ctx")["fixes"]


def test_cut_off_output_is_reported_and_falls_back(keys, monkeypatch):
    route(monkeypatch, {"googleapis": Resp(body=gemini_body('{"fixes": [', finish="MAX_TOKENS")),
                        "anthropic": Resp(body=claude_body(json.dumps(GOOD)))})
    assert ai.propose_fixes("ctx")["fixes"]


def test_no_credits_error_is_plain_language(keys, monkeypatch):
    credit = Resp(400, text='{"type":"error","error":{"message":"Your credit balance is too low to access the Anthropic API."}}')
    route(monkeypatch, {"googleapis": Resp(body=gemini_body("")), "anthropic": credit,
                        "groq.com": Resp(429, text="rate limit reached")})
    with pytest.raises(ai.CodeFixAIError) as e:
        ai.propose_fixes("ctx")
    msg = str(e.value)
    assert "gemini: the model returned an empty reply" in msg
    assert "claude: the account has no credits left" in msg
    assert "groq: rate limit or quota reached" in msg
    assert "request_id" not in msg


def test_groq_is_the_last_resort(keys, monkeypatch):
    groq = Resp(body={"choices": [{"message": {"content": json.dumps(GOOD)}, "finish_reason": "stop"}]})
    calls = route(monkeypatch, {"googleapis": Resp(500, text="boom"), "anthropic": Resp(500, text="boom"), "groq.com": groq})
    assert ai.propose_fixes("ctx")["fixes"] and calls[-1] == "groq.com"


def test_no_keys_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(ai, "API_KEYS", {})
    with pytest.raises(ai.CodeFixAIError, match="no AI provider is configured"):
        ai.propose_fixes("ctx")