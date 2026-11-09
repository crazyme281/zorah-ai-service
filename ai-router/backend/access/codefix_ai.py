"""
Code Fixer's own AI call — deliberately separate from router.py's
conversational chat pipeline. No persona, no emotion engine, no chat
history; one structured request in, one structured JSON response out.

Provider order is what the spec asks for: Gemini, then Claude, then
OpenAI, with Groq as a last resort - and only providers whose key is
actually configured are tried at all, per "do not assume a provider is
free." A provider that fails (no credits, rate limit, empty or cut-off
reply, reply that isn't JSON) is skipped for the next one, and the error
shown to the user says in plain words what went wrong with each.
"""

import json
import os
import re

import requests

from config import API_KEYS, MODELS

PROVIDER_ORDER = ["gemini", "claude", "openai", "groq"]
# Rewriting a whole project is far slower than a chat reply (a thinking model
# can think for minutes first), so this has its own, much longer, timeout.
# The job runs in the background; nobody is waiting on this one request.
REQUEST_TIMEOUT = int(os.getenv("CODE_FIXER_AI_TIMEOUT", "240"))
MAX_OUTPUT_TOKENS = 32768   # thinking models spend part of this before writing the answer

SYSTEM_PROMPT = """You are a careful software engineer fixing a real, existing project.

Rules:
- Only fix concrete, identifiable problems: syntax errors, broken imports, type errors, obvious bugs, misconfigured files, dependency issues.
- Do NOT rewrite working code, redesign anything, or refactor beyond what's needed to fix an identified problem.
- Preserve the project's existing structure and style.
- Only touch files you're actually fixing — never include a file's content unless you changed it.
- For each fixed file, return its COMPLETE new content, not a diff or a snippet.
- If you cannot find any real, fixable problem, return an empty "fixes" list — never invent a problem to seem useful.

Respond with ONLY a single JSON object, no markdown fences, no commentary, in exactly this shape:
{
  "problems": ["short description of each real problem found"],
  "fixes": [
    {"path": "relative/path/as/given.ext", "new_content": "...", "reason": "one line explaining the fix"}
  ],
  "dependencies": {"add": ["pkgname"], "remove": [], "update": ["pkgname"]}
}"""


class CodeFixAIError(Exception):
    pass


def propose_fixes(project_context: str, extra_instruction: str = "") -> dict:
    """
    Sends the gathered project context to the first configured provider
    in PROVIDER_ORDER, falling back to the next on any failure — rate
    limit, timeout, API error, or a response that doesn't parse as the
    JSON shape above. Raises CodeFixAIError only if every configured
    provider fails; if NO provider is configured at all, that's also a
    CodeFixAIError, not a silent no-op.
    """
    configured = [p for p in PROVIDER_ORDER if API_KEYS.get(p)]
    if not configured:
        raise CodeFixAIError("no AI provider is configured (GEMINI_API_KEY/CLAUDE_API_KEY/OPENAI_API_KEY/GROQ_API_KEY)")

    user_content = project_context
    if extra_instruction:
        user_content = f"{extra_instruction}\n\n{project_context}"

    attempts: list[tuple[str, str]] = []
    for provider in configured:
        content = user_content
        for try_no in (1, 2):
            try:
                return _parse_json_response(_CALLERS[provider](content))
            except _BadReply as e:
                # The model answered but not with usable JSON: one retry that
                # says so, then move on to the next provider.
                err = str(e)
                if try_no == 1:
                    content = (user_content + "\n\nYour previous reply could not be used (" + err
                               + "). Reply again with ONLY the JSON object described, nothing else.")
                    continue
                attempts.append((provider, err))
            except Exception as e:
                attempts.append((provider, _friendly(str(e))))
            break

    summary = "; ".join(f"{name}: {err}" for name, err in attempts)
    raise CodeFixAIError(f"no AI provider could fix this project. {summary}")


class _BadReply(Exception):
    """The provider answered, but not with usable JSON (empty, cut off, prose)."""


def _friendly(err: str) -> str:
    """Short, readable reason for a provider failure (raw detail kept, trimmed)."""
    low = err.lower()
    if "credit balance" in low:
        return "the account has no credits left - add credits in its billing page"
    if "timed out" in low or "timeout" in low:
        return f"took longer than {REQUEST_TIMEOUT} seconds to answer - the project may be too big for one pass"
    if "429" in low or "quota" in low or "rate limit" in low or "resource_exhausted" in low:
        return "rate limit or quota reached - try again in a minute"
    if "401" in low or "403" in low or "api key" in low or "permission" in low:
        return "the API key was rejected - check it in your environment settings"
    if "413" in low or "too large" in low or "context" in low and "length" in low:
        return "the project is too large for this model"
    return err[:200]


def _parse_json_response(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise _BadReply("the model returned an empty reply")
    if "```" in cleaned:  # a markdown fence, anywhere in the reply
        m = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
        cleaned = (m.group(1) if m else cleaned.replace("```json", "").replace("```", "")).strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        # Prose before/after the JSON: take from the first { to the last }.
        i, j = cleaned.find("{"), cleaned.rfind("}")
        if i == -1:
            raise _BadReply("the reply was not JSON")
        if j <= i:
            raise _BadReply("the reply was cut off or malformed JSON")
        try:
            data = json.loads(cleaned[i:j + 1])
        except ValueError:
            raise _BadReply("the reply was cut off or malformed JSON")
    if not isinstance(data, dict) or "fixes" not in data:
        raise _BadReply("the reply had no 'fixes' list")
    data.setdefault("problems", [])
    data.setdefault("dependencies", {})
    if not isinstance(data["fixes"], list):
        raise _BadReply("'fixes' was not a list")
    return data


def _call_gemini(user_content: str) -> str:
    model = MODELS["gemini"]
    key = API_KEYS["gemini"]
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"gemini: HTTP {resp.status_code} - {resp.text[:300]}")
    data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        raise _BadReply(f"gemini returned no answer{f' (blocked: {block})' if block else ''}")
    cand = cands[0]
    # Skip "thought" parts of thinking models; keep only the written answer.
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if cand.get("finishReason") == "MAX_TOKENS":
        raise _BadReply("gemini ran out of output space before finishing")
    return text


def _call_claude(user_content: str) -> str:
    key = API_KEYS["claude"]
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json={
            "model": MODELS["claude"],
            "max_tokens": 8192,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"claude: HTTP {resp.status_code} - {resp.text[:300]}")
    data = resp.json()
    if data.get("stop_reason") == "max_tokens":
        raise _BadReply("claude ran out of output space before finishing")
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(user_content: str) -> str:
    key = API_KEYS["openai"]
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": MODELS["openai"],
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"openai: HTTP {resp.status_code} - {resp.text[:300]}")
    data = resp.json()
    if data["choices"][0].get("finish_reason") == "length":
        raise _BadReply("openai ran out of output space before finishing")
    return data["choices"][0]["message"]["content"]


def _call_groq(user_content: str) -> str:
    """Last resort. Groq's free tier caps tokens per minute, so a large
    project may be refused here - that is reported, not hidden."""
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEYS['groq']}", "Content-Type": "application/json"},
        json={
            "model": MODELS["groq"],
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"groq: HTTP {resp.status_code} - {resp.text[:300]}")
    data = resp.json()
    if data["choices"][0].get("finish_reason") == "length":
        raise _BadReply("groq ran out of output space before finishing")
    return data["choices"][0]["message"]["content"]


_CALLERS = {"gemini": _call_gemini, "claude": _call_claude, "openai": _call_openai, "groq": _call_groq}