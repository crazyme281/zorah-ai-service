import requests
from providers.base import BaseProvider
from utils.errors import RateLimitError, ProviderUnavailableError
from utils.multimodal import to_anthropic_blocks
from config import API_KEYS, MODELS, REQUEST_TIMEOUT

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class ClaudeProvider(BaseProvider):
    name = "claude"

    def chat(self, messages: list[dict], **kwargs) -> str:
        headers = {
            "x-api-key": API_KEYS["claude"],
            "anthropic-version": API_VERSION,
            "Content-Type": "application/json",
        }

        # Anthropic's Messages API takes the system prompt as its own
        # top-level field rather than a {"role": "system"} entry inside
        # the messages list — pull any system turns out before sending.
        system_parts = [m["content"] for m in messages if m["role"] == "system"]

        # Content may be a plain string or a list of {text|image_url}
        # blocks (once an attachment is involved) — to_anthropic_blocks
        # normalizes either shape into Anthropic's block format, turning
        # any image into a base64 `source` since Claude's public API
        # can't fetch a URL itself.
        chat_messages = [
            {"role": m["role"], "content": to_anthropic_blocks(m["content"])}
            for m in messages
            if m["role"] != "system"
        ]

        payload = {
            "model": kwargs.get("model", MODELS["claude"]),
            "messages": chat_messages,
            "max_tokens": kwargs.get("max_tokens", 1024),
            "temperature": kwargs.get("temperature", 0.7),
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        try:
            resp = requests.post(
                ENDPOINT, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise ProviderUnavailableError(f"claude: request failed ({e})")

        if resp.status_code == 429:
            raise RateLimitError("claude: rate limited")
        if resp.status_code >= 400:
            raise ProviderUnavailableError(f"claude: HTTP {resp.status_code} - {resp.text[:200]}")

        data = resp.json()
        try:
            return "".join(
                block["text"] for block in data["content"] if block.get("type") == "text"
            )
        except (KeyError, IndexError) as e:
            raise ProviderUnavailableError(f"claude: malformed response ({e})")