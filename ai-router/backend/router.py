"""
The router owns exactly one job: given a classified intent and a
conversation, try the primary provider, and on failure walk the
fallback list in order. It never decides *why* a provider failed
beyond rate-limit vs. unavailable — that distinction exists so you
can log/alert on rate limits differently from outright outages.
"""
import logging
import time
from config import ROUTES
from classifier import classify
from utils.errors import RateLimitError, ProviderUnavailableError, AllProvidersFailedError
from utils.multimodal import extract_text, has_image
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore
from identity import IDENTITY_SYSTEM_PROMPT, is_identity_question, identity_reply
import learned
from control import Controls, get_controls

from providers.claude_provider import ClaudeProvider
from providers.gemini_provider import GeminiProvider
from providers.zai_provider import ZaiProvider
from providers.groq_provider import GroqProvider
from providers.cohere_provider import CohereProvider

logger = logging.getLogger("ai_router")

PROVIDERS = {
    "claude": ClaudeProvider(),
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

# The only providers whose .chat() actually converts an image block into
# something the model can see (see utils/multimodal.py). Every other
# provider is OpenAI-compatible and will happily accept the same block
# shape without erroring, but there's no guarantee the model behind it
# is vision-capable — so a message with an attachment always tries
# these first, regardless of what the text classifier says.
VISION_CAPABLE = ["claude", "gemini"]


class AIRouter:
    def __init__(
        self,
        providers: dict = None,
        routes: dict = None,
        emotion_engine: EmotionEngine = None,
        subscriptions: SubscriptionStore = None,
        controls: Controls = None,
    ):
        self.providers = providers or PROVIDERS
        self.routes = routes or ROUTES
        # Only constructed if persona mode actually gets used — no cost
        # to routers that never touch emotion.
        self.emotion_engine = emotion_engine
        # If None, no tier gating is applied — every provider is reachable.
        # Pass a real SubscriptionStore (backed by your DB) to enforce it.
        self.subscriptions = subscriptions
        # Kill switch, budget caps, circuit breakers, decision records. Shared
        # process-wide by default; tests pass their own.
        self._controls = controls

    @property
    def controls(self) -> Controls:
        return self._controls or get_controls()

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

    def _build_chain(self, route, messages: list[dict], user_id: str) -> list[str]:
        chain = [route.primary] + route.fallbacks
        if has_image(messages):
            # Move whichever vision-capable providers exist to the front,
            # keeping the rest of the classified chain as a fallback in
            # case both vision providers are down (it'll likely fail on
            # a non-vision model, but that's the same "walk the chain
            # and surface the real error" behavior as any other outage).
            vision_first = [p for p in VISION_CAPABLE if p in self.providers]
            chain = vision_first + [p for p in chain if p not in vision_first]
        return self._filter_chain_for_tier(chain, user_id)

    def _flatten_text_only(self, messages: list[dict]) -> list[dict]:
        """
        Collapses any message carrying an image block down to its text
        portion plus a plain note that an image was attached — used only
        for providers that aren't in VISION_CAPABLE, right before calling
        them, so they get something they can actually parse instead of a
        content shape their API rejects outright.
        """
        flat = []
        for m in messages:
            content = m["content"]
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "image_url" for b in content
            ):
                text = extract_text(content)
                note = "[The user attached an image, but this model can't see it.]"
                flat.append({**m, "content": f"{text}\n\n{note}".strip() if text else note})
            else:
                flat.append(m)
        return flat

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
        messages: full conversation so far, last item is the newest user
            turn. Each message's "content" is either a plain string or a
            list of {"type": "text"|"image_url", ...} blocks (once an
            attachment is involved) — see utils/multimodal.py.
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
        started = time.monotonic()
        user_text = extract_text(messages[-1]["content"]) if messages else ""
        intent = intent or self.route_for(user_text)
        route = self.routes.get(intent, self.routes["default"])
        image_present = has_image(messages)
        ctl = self.controls
        in_chars = sum(len(extract_text(m["content"])) for m in messages)

        def record(provider, ok, attempts=(), confidence=None, out_chars=0):
            """One decision record per turn (no message text is stored)."""
            try:
                ctl.observability.record(
                    intent=intent, provider=provider, ok=ok,
                    latency_ms=(time.monotonic() - started) * 1000, attempts=len(attempts),
                    failed=[a[0] for a in attempts], confidence=confidence, persona=persona,
                    has_image=image_present, in_chars=in_chars, out_chars=out_chars, session_id=session_id)
            except Exception:  # observability must never break chat
                logger.warning("could not record decision", exc_info=True)

        # "Which model are you?" is answered locally with the app's display
        # name so a provider's own name can never leak. No provider is called.
        if not image_present and is_identity_question(user_text):
            reply = identity_reply(user_text)
            record("identity", True, out_chars=len(reply))
            return {
                "reply": reply,
                "provider": "identity",
                "intent": "identity",
                "attempts": [],
                "emotion": None,
            }

        # Learned knowledge: answer from it only when it is sure. When it is
        # not sure (or the question is outside what it learned) the message
        # continues to the normal provider chain below, unchanged.
        if not image_present:
            hit = learned.answer_if_confident(user_text)
            if hit:
                record("learned", True, confidence=hit["confidence"], out_chars=len(hit["reply"]))
                return {
                    "reply": hit["reply"],
                    "provider": "learned",
                    "intent": "learned",
                    "attempts": [],
                    "emotion": None,
                    "confidence": hit["confidence"],
                }

        call_messages = messages
        emotion_snapshot = None
        if persona:
            if self.emotion_engine is None:
                self.emotion_engine = EmotionEngine()
            directive = self.emotion_engine.process_turn(session_id, user_text)
            call_messages = self._inject_directive(messages, directive)
            emotion_snapshot = self.emotion_engine.snapshot(session_id)

        # Tell whichever provider answers what the assistant is called.
        call_messages = self._inject_directive(call_messages, IDENTITY_SYSTEM_PROMPT)

        chain = self._build_chain(route, call_messages, user_id)
        attempts = []
        image_present = has_image(call_messages)

        def try_provider(provider_name: str):
            """Returns the reply, or None after noting why this provider was not used."""
            provider = self.providers.get(provider_name)
            if provider is None:
                attempts.append((provider_name, "not configured"))
                return None
            # A provider outside VISION_CAPABLE has no way to parse an
            # image block - Groq/Z.ai/Cohere all hard-400 the instant they
            # see one. Strip the image down to a text note instead, so a
            # non-vision fallback can still answer the text part.
            provider_messages = call_messages
            if image_present and provider_name not in VISION_CAPABLE:
                provider_messages = self._flatten_text_only(call_messages)
            try:
                reply = provider.chat(provider_messages, **kwargs)
            except RateLimitError as e:
                logger.warning("Rate limited: %s", e)
                attempts.append((provider_name, str(e)))
                ctl.breaker.failure(provider_name, str(e))
                return None
            except ProviderUnavailableError as e:
                logger.warning("Provider unavailable: %s", e)
                attempts.append((provider_name, str(e)))
                ctl.breaker.failure(provider_name, str(e))
                return None
            except Exception as e:  # an unexpected provider bug must not end the whole chain
                logger.exception("Provider %s raised unexpectedly", provider_name)
                attempts.append((provider_name, f"{type(e).__name__}: {str(e)[:120]}"))
                ctl.breaker.failure(provider_name, f"{type(e).__name__}")
                return None
            ctl.breaker.success(provider_name)
            ctl.budget.record(provider_name, in_chars, len(reply) if isinstance(reply, str) else 0)
            return reply

        reply, answered_by, circuit_skipped = None, None, []
        for provider_name in chain:
            ok, why = ctl.budget.check(provider_name)
            if not ok:  # hard spending cap: never retried, even as a last resort
                attempts.append((provider_name, f"budget: {why}"))
                continue
            if not ctl.breaker.allow(provider_name):
                attempts.append((provider_name, "circuit open"))
                circuit_skipped.append(provider_name)
                continue
            reply = try_provider(provider_name)
            if reply is not None:
                answered_by = provider_name
                break

        # Last resort: if every provider was skipped only because its circuit
        # was open, try them anyway rather than failing without a single call.
        if answered_by is None and circuit_skipped and len(attempts) == len(circuit_skipped) + sum(
                1 for a in attempts if a[1].startswith("budget:")):
            for provider_name in circuit_skipped:
                reply = try_provider(provider_name)
                if reply is not None:
                    answered_by = provider_name
                    break

        if answered_by is None:
            record(None, False, attempts)
            raise AllProvidersFailedError(intent, attempts)

        # Remember vetted standalone Q&A so the learned model can answer
        # it next time (never raises; see learned/chat_learning.py).
        if (not image_present and isinstance(reply, str)
                and sum(1 for m in messages if m.get("role") == "user") == 1):
            learned.record_fallback(user_text, reply, answered_by, session_id)
        record(answered_by, True, attempts, out_chars=len(reply) if isinstance(reply, str) else 0)
        return {
            "reply": reply,
            "provider": answered_by,
            "intent": intent,
            "attempts": attempts,
            "emotion": emotion_snapshot,
        }