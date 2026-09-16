"""
Interactive CLI for the multi-provider AI router.

Run: python main.py
Type 'exit' to quit, 'reset' to clear conversation history,
'tier free' / 'tier pro' to switch subscription tier for testing.
"""
import logging
import sys

from config import missing_keys
from router import AIRouter
from emotion.engine import EmotionEngine
from access.tiers import SubscriptionStore, Tier
from branding import scrub_result_for_user
from utils.errors import AllProvidersFailedError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

SESSION_ID = "cli-user"
USER_ID = "cli-user"


def main():
    gaps = missing_keys()
    if gaps:
        print(f"Warning: missing API keys for: {', '.join(gaps)}")
        print("Those providers will fail if selected as primary or fallback.\n")

    emotion_engine = EmotionEngine()
    subscriptions = SubscriptionStore()  # defaults everyone to FREE until set
    router = AIRouter(emotion_engine=emotion_engine, subscriptions=subscriptions)
    history: list[dict] = []
    persona = True

    print("AI Router — type 'exit' to quit, 'reset' to clear history,")
    print("'mood' to see current emotional state, 'persona off/on' to toggle it,")
    print("'tier free' / 'tier pro' to switch subscription tier.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if not user_input:
            continue
        if user_input.lower() == "exit":
            break
        if user_input.lower() == "reset":
            history = []
            emotion_engine.reset(SESSION_ID)
            print("(history and mood cleared)\n")
            continue
        if user_input.lower() == "mood":
            snap = emotion_engine.snapshot(SESSION_ID)
            print("Current mood:", {k: round(v, 2) for k, v in snap.items()}, "\n")
            continue
        if user_input.lower() in ("persona off", "persona on"):
            persona = user_input.lower().endswith("on")
            print(f"(persona mode {'enabled' if persona else 'disabled'})\n")
            continue
        if user_input.lower() in ("tier free", "tier pro"):
            tier = Tier.PRO if user_input.lower().endswith("pro") else Tier.FREE
            # NOTE: this is a dev shortcut for local testing only. In
            # production, set_tier is only ever called from
            # access.payments.upgrade_to_pro after a verified charge —
            # never from a raw user command like this.
            subscriptions.set_tier(USER_ID, tier)
            print(f"(tier set to {tier.value} — dev-only shortcut, not how it works in prod)\n")
            continue

        history.append({"role": "user", "content": user_input})

        try:
            result = router.chat(history, persona=persona, session_id=SESSION_ID, user_id=USER_ID)
        except AllProvidersFailedError as e:
            print(f"\n[All providers failed] {e}\n")
            history.pop()  # don't poison history with a failed turn
            continue

        reply = result["reply"]
        history.append({"role": "assistant", "content": reply})

        user_facing = scrub_result_for_user(result)
        # [debug] line shows real routing — this is what YOU see as the
        # developer. End users should only ever see user_facing['model_label'].
        print(f"\n[debug: {result['intent']} -> {result['provider']}]")
        print(f"{user_facing['model_label']}: {reply}\n")


if __name__ == "__main__":
    main()
