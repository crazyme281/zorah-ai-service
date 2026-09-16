class ProviderError(Exception):
    """Base class for any failure raised by a provider client."""


class RateLimitError(ProviderError):
    """Provider returned a 429 / quota-exceeded style response."""


class ProviderUnavailableError(ProviderError):
    """Provider timed out, errored, or the request otherwise couldn't complete."""


class AllProvidersFailedError(Exception):
    """Every provider in a route's primary+fallback chain failed."""

    def __init__(self, intent: str, attempts: list[tuple[str, Exception]]):
        self.intent = intent
        self.attempts = attempts
        summary = ", ".join(f"{name}: {err}" for name, err in attempts)
        super().__init__(f"All providers failed for intent '{intent}' -> {summary}")
