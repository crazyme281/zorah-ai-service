import requests
from providers.base import BaseProvider
from utils.errors import RateLimitError, ProviderUnavailableError
from utils.multimodal import to_gemini_parts
from config import API_KEYS, MODELS, REQUEST_TIMEOUT


def _endpoint(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(BaseProvider):
    name = "gemini"

    def chat(self, messages: list[dict], **kwargs) -> str:
        model = kwargs.get("model", MODELS["gemini"])

        # Gemini splits out a system instruction and expects
        # user/model roles (not user/assistant) inside "contents".
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            # to_gemini_parts handles both plain string content and a
            # {text|image_url} block list, converting any image into
            # inline_data base64 since Gemini can't fetch a URL itself.
            contents.append({"role": role, "parts": to_gemini_parts(m["content"])})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 2048),
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

        try:
            resp = requests.post(
                _endpoint(model),
                params={"key": API_KEYS["gemini"]},
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            raise ProviderUnavailableError(f"gemini: request failed ({e})")

        if resp.status_code == 429:
            raise RateLimitError("gemini: rate limited")
        if resp.status_code >= 400:
            raise ProviderUnavailableError(f"gemini: HTTP {resp.status_code} - {resp.text[:200]}")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderUnavailableError(f"gemini: malformed response ({e})")