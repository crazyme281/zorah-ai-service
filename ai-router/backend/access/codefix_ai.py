"""
Code Fixer's own AI call — deliberately separate from router.py's
conversational chat pipeline. No persona, no emotion engine, no chat
history; one structured request in, one structured JSON response out.

Provider order is exactly what the spec asks for: Gemini, then Claude,
then OpenAI — and only providers whose key is actually configured are
tried at all, per "do not assume a provider is free."
"""

import json
import re

import requests

from config import API_KEYS, MODELS, REQUEST_TIMEOUT

PROVIDER_ORDER = ["gemini", "claude", "openai"]

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
        raise CodeFixAIError("no AI provider is configured (GEMINI_API_KEY/CLAUDE_API_KEY/OPENAI_API_KEY)")

    user_content = project_context
    if extra_instruction:
        user_content = f"{extra_instruction}\n\n{project_context}"

    attempts: list[tuple[str, str]] = []
    for provider in configured:
        try:
            raw = _CALLERS[provider](user_content)
            return _parse_json_response(raw)
        except Exception as e:
            attempts.append((provider, str(e)))

    summary = ", ".join(f"{name}: {err}" for name, err in attempts)
    raise CodeFixAIError(f"all AI providers failed -> {summary}")


def _parse_json_response(raw: str) -> dict:
    cleaned = raw.strip()
    # Strip a markdown fence if the model added one despite instructions.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict) or "fixes" not in data:
        raise ValueError("response JSON missing required 'fixes' key")
    data.setdefault("problems", [])
    data.setdefault("dependencies", {})
    return data


def _call_gemini(user_content: str) -> str:
    model = MODELS["gemini"]
    key = API_KEYS["gemini"]
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"maxOutputTokens": 8192, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"gemini: HTTP {resp.status_code} - {resp.text[:300]}")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


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
    return data["choices"][0]["message"]["content"]


_CALLERS = {"gemini": _call_gemini, "claude": _call_claude, "openai": _call_openai}