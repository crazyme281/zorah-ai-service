import requests
from providers.base import BaseProvider
from utils.errors import RateLimitError, ProviderUnavailableError
from config import API_KEYS, MODELS, REQUEST_TIMEOUT

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(BaseProvider):
    name = "groq"

    def chat(self, messages: list[dict], **kwargs) -> str:
        headers = {
            "Authorization": f"Bearer {API_KEYS['groq']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": kwargs.get("model", MODELS["groq"]),
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        try:
            resp = requests.post(
                ENDPOINT, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise ProviderUnavailableError(f"groq: request failed ({e})")

        if resp.status_code == 429:
            raise RateLimitError("groq: rate limited")
        if resp.status_code >= 400:
            raise ProviderUnavailableError(f"groq: HTTP {resp.status_code} - {resp.text[:200]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderUnavailableError(f"groq: malformed response ({e})")