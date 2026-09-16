import requests
from providers.base import BaseProvider
from utils.errors import RateLimitError, ProviderUnavailableError
from config import API_KEYS, MODELS, REQUEST_TIMEOUT

BASE = "https://api.cohere.com/v1"


class CohereProvider(BaseProvider):
    name = "cohere"

    def _headers(self):
        return {
            "Authorization": f"Bearer {API_KEYS['cohere']}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = requests.post(
                f"{BASE}/{path}", headers=self._headers(), json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise ProviderUnavailableError(f"cohere: request failed ({e})")

        if resp.status_code == 429:
            raise RateLimitError("cohere: rate limited")
        if resp.status_code >= 400:
            raise ProviderUnavailableError(f"cohere: HTTP {resp.status_code} - {resp.text[:200]}")
        return resp.json()

    def chat(self, messages: list[dict], **kwargs) -> str:
        # Cohere's chat endpoint wants the latest user turn separate
        # from history.
        history = [
            {"role": "USER" if m["role"] == "user" else "CHATBOT", "message": m["content"]}
            for m in messages[:-1]
            if m["role"] in ("user", "assistant")
        ]
        latest = messages[-1]["content"]
        payload = {
            "model": kwargs.get("model", MODELS["cohere_chat"]),
            "message": latest,
            "chat_history": history,
        }
        data = self._post("chat", payload)
        try:
            return data["text"]
        except KeyError as e:
            raise ProviderUnavailableError(f"cohere: malformed chat response ({e})")

    def embed(self, texts: list[str], input_type: str = "search_document") -> list[list[float]]:
        payload = {
            "model": MODELS["cohere_embed"],
            "texts": texts,
            "input_type": input_type,
        }
        data = self._post("embed", payload)
        try:
            return data["embeddings"]
        except KeyError as e:
            raise ProviderUnavailableError(f"cohere: malformed embed response ({e})")

    def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        payload = {
            "model": MODELS["cohere_rerank"],
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
        data = self._post("rerank", payload)
        try:
            return data["results"]  # [{index, relevance_score}, ...]
        except KeyError as e:
            raise ProviderUnavailableError(f"cohere: malformed rerank response ({e})")
