"""
The router owns exactly one job: given a classified intent and a
conversation, try the primary provider, and on failure walk the
fallback list in order. It never decides *why* a provider failed
beyond rate-limit vs. unavailable — that distinction exists so you
can log/alert on rate limits differently from outright outages.
"""
import logging
from config import ROUTES
from classifier import classify
from utils.errors import RateLimitError, ProviderUnavailableError, AllProvidersFailedError
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore

from providers.together_provider import TogetherProvider
from providers.gemini_provider import GeminiProvider
from providers.zai_provider import ZaiProvider
from providers.groq_provider import GroqProvider
from providers.cohere_provider import CohereProvider

logger = logging.getLogger("ai_router")

PROVIDERS = {
    "together": TogetherProvider(),
    "gemini": GeminiProvider(),
    "zai": ZaiProvider(),
    "groq": GroqProvider(),
    "cohere": CohereProvider(),
}

# Providers gated behind entitlements rather than open to every tier.
# Checked against access.tiers.Entitlements field names.
TIER_GATED_PROVIDERS = {
    "groq": "can_use_groq_fast_lane",
}


class AIRouter:
    def __init__(
        self,
        providers: dict = None,
        routes: dict = None,
        emotion_engine: EmotionEngine = None,
        subscriptions: SubscriptionStore = None,
    ):
        self.providers = providers or PROVIDERS
        self.routes = routes or ROUTES
        # Only constructed if persona mode actually gets used — no cost
        # to routers that never touch emotion.
        self.emotion_engine = emotion_engine
        # If None, no tier gating is applied — every provider is reachable.
        # Pass a real SubscriptionStore (backed by your DB) to enforce it.
        self.subscriptions = subscriptions

    def route_for(self, message: str) -> str:
        return classify(message)

    def _inject_directive(self, messages: list[dict], directive: str) -> list[dict]:
        """
        Returns a NEW messages list with the emotion directive folded into
        the system message. Never mutates the caller's stored history —
        the directive is regenerated fresh every turn from current state,
        so it should never be persisted alongside the conversation.
        """
        call_messages = [dict(m) for m in messages]
        existing_system = next((m for m in call_messages if m["role"] == "system"), None)
        if existing_system:
            existing_system["content"] = f"{existing_system['content']}\n\n{directive}"
        else:
            call_messages.insert(0, {"role": "system", "content": directive})
        return call_messages

    def _filter_chain_for_tier(self, chain: list[str], user_id: str) -> list[str]:
        """
        Drops any provider this user's tier isn't entitled to (e.g. Groq
        for FREE users) from the fallback chain. Subscription state is
        always looked up server-side via self.subscriptions — nothing
        about tier is ever read from kwargs or trusted from the caller.
        """
        if self.subscriptions is None or user_id is None:
            return chain
        entitlements = self.subscriptions.entitlements_for(user_id)
        return [
            name for name in chain
            if name not in TIER_GATED_PROVIDERS
            or getattr(entitlements, TIER_GATED_PROVIDERS[name])
        ]

    def chat(
        self,
        messages: list[dict],
        intent: str = None,
        persona: bool = False,
        session_id: str = "default",
        user_id: str = None,
        **kwargs,
    ) -> dict:
        """
        messages: full conversation so far, last item is the newest user turn.
        intent: override the classifier if you already know the route.
        persona: if True, runs the emotion engine and injects a behavioral
            directive as a system message before calling the provider.
            Requires an EmotionEngine to have been passed to __init__.
        session_id: which emotional state to use/update — one per user or
            conversation thread.
        user_id: which subscriber's entitlements to enforce. If a
            SubscriptionStore was passed to __init__ and user_id is given,
            tier-gated providers (Groq) are dropped from the chain when
            this user isn't entitled to them.
        Returns {"reply": str, "provider": str, "intent": str, "attempts": [...],
                 "emotion": {...} or None}
        """
        user_text = messages[-1]["content"] if messages else ""
        intent = intent or self.route_for(user_text)
        route = self.routes.get(intent, self.routes["default"])

        call_messages = messages
        emotion_snapshot = None
        if persona:
            if self.emotion_engine is None:
                self.emotion_engine = EmotionEngine()
            directive = self.emotion_engine.process_turn(session_id, user_text)
            call_messages = self._inject_directive(messages, directive)
            emotion_snapshot = self.emotion_engine.snapshot(session_id)

        chain = [route.primary] + route.fallbacks
        chain = self._filter_chain_for_tier(chain, user_id)
        attempts = []

        for provider_name in chain:
            provider = self.providers.get(provider_name)
            if provider is None:
                attempts.append((provider_name, "not configured"))
                continue
            try:
                reply = provider.chat(call_messages, **kwargs)
                return {
                    "reply": reply,
                    "provider": provider_name,
                    "intent": intent,
                    "attempts": attempts,
                    "emotion": emotion_snapshot,
                }
            except RateLimitError as e:
                logger.warning("Rate limited: %s", e)
                attempts.append((provider_name, str(e)))
                continue
            except ProviderUnavailableError as e:
                logger.warning("Provider unavailable: %s", e)
                attempts.append((provider_name, str(e)))
                continue

        raise AllProvidersFailedError(intent, attempts)
