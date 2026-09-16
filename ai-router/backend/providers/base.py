from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """
    Every provider wrapper exposes the same .chat() signature so the
    router can call any of them interchangeably without knowing which
    SDK or REST shape sits underneath.
    """

    name: str = "base"

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        """
        messages: list of {"role": "user"|"assistant"|"system", "content": str}
        Returns the assistant's reply text.
        Raises RateLimitError or ProviderUnavailableError on failure.
        """
        raise NotImplementedError
