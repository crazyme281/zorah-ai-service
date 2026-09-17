import requests
from providers.base import BaseProvider
from utils.errors import RateLimitError, ProviderUnavailableError
from config import API_KEYS, MODELS, REQUEST_TIMEOUT

ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"


class ZaiProvider(BaseProvider):
    name = "zai"

    def chat(self, messages: list[dict], **kwargs) -> str:
        headers = {
            "Authorization": f"Bearer {API_KEYS['zai']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", MODELS["zai"]),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        # Pass tools through untouched if the caller supplied them —
        # this is what makes zai usable as the "agent" primary.
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]

        try:
            resp = requests.post(
                ENDPOINT, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise ProviderUnavailableError(f"zai: request failed ({e})")

        if resp.status_code == 429:
            raise RateLimitError("zai: rate limited")
        if resp.status_code >= 400:
            raise ProviderUnavailableError(f"zai: HTTP {resp.status_code} - {resp.text[:200]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderUnavailableError(f"zai: malformed response ({e})")