"""
FREE / GO / PRO entitlements.

Subscription state is read from and written to Supabase (via
access/db.py, using the service role key) — never taken as a claim
passed in from the client. There is deliberately no
"trust_frontend_tier" parameter anywhere in this file; if you're
tempted to add one for convenience, don't.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from access.db import select, upsert

GRACE_PERIOD_DAYS = 2


class Tier(str, Enum):
    FREE = "FREE"
    GO = "GO"
    PRO = "PRO"


@dataclass(frozen=True)
class Entitlements:
    daily_image_uploads: int
    can_generate_images: bool
    can_use_groq_fast_lane: bool
    can_generate_pptx: bool
    can_generate_pdf: bool
    can_generate_docx: bool
    higher_reasoning: bool


ENTITLEMENTS = {
    Tier.FREE: Entitlements(
        daily_image_uploads=6,
        can_generate_images=False,
        can_use_groq_fast_lane=False,
        can_generate_pptx=False,
        can_generate_pdf=False,
        can_generate_docx=False,
        higher_reasoning=False,
    ),
    Tier.GO: Entitlements(
        daily_image_uploads=10,
        can_generate_images=False,
        can_use_groq_fast_lane=True,
        can_generate_pptx=False,
        can_generate_pdf=False,
        can_generate_docx=False,
        higher_reasoning=False,
    ),
    Tier.PRO: Entitlements(
        daily_image_uploads=15,
        can_generate_images=True,
        can_use_groq_fast_lane=True,
        can_generate_pptx=True,
        can_generate_pdf=True,
        can_generate_docx=True,
        higher_reasoning=True,
    ),
}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class SubscriptionStore:
    """
    Reads/writes the `profiles` table in Supabase (see the migration
    that ships alongside this file). Tier is only ever changed by
    set_tier() — called after a verified payment, see
    access/payments.py — or by the automatic expiration sweep in
    get_tier() that drops a lapsed subscription back to FREE.
    """

    def get_profile(self, user_id: str) -> dict:
        rows = select("profiles", {"user_id": f"eq.{user_id}", "select": "*"})
        if rows:
            return rows[0]
        # No row yet — this user hasn't completed plan selection/
        # onboarding. Treat as FREE without writing anything; the row
        # is created by set_free() or set_tier(), not by reading.
        return {
            "user_id": user_id,
            "tier": Tier.FREE.value,
            "subscription_status": "none",
            "subscription_start": None,
            "subscription_expiration": None,
            "grace_period_expiration": None,
            "onboarding_completed": False,
        }

    def get_tier(self, user_id: str) -> Tier:
        profile = self.get_profile(user_id)
        tier = Tier(profile.get("tier") or Tier.FREE.value)
        if tier == Tier.FREE:
            return tier

        # A paid tier only counts while still inside the subscription
        # window or its grace period — the server-side check the spec
        # requires, so a user can't stay "Pro" by editing their device
        # clock or local storage. Falling through this check flips
        # them back to FREE right here, the moment anything asks.
        expiration = profile.get("grace_period_expiration") or profile.get("subscription_expiration")
        if expiration is None:
            return tier
        if datetime.now(timezone.utc) > _parse(expiration):
            self.downgrade_to_free(user_id)
            return Tier.FREE
        return tier

    def status_for(self, user_id: str) -> dict:
        """What the frontend needs to render plan/expiration state."""
        profile = self.get_profile(user_id)
        tier = self.get_tier(user_id)  # runs the expiration check first
        return {
            "tier": tier.value,
            "subscription_status": profile.get("subscription_status", "none"),
            "subscription_expiration": profile.get("subscription_expiration"),
            "grace_period_expiration": profile.get("grace_period_expiration"),
            "onboarding_completed": profile.get("onboarding_completed", False),
        }

    def set_tier(
        self,
        user_id: str,
        tier: Tier,
        subscription_start: datetime,
        subscription_expiration: datetime,
    ):
        """Only ever called after a verified payment — see access/payments.py."""
        grace = subscription_expiration + timedelta(days=GRACE_PERIOD_DAYS)
        upsert(
            "profiles",
            {
                "user_id": user_id,
                "tier": tier.value,
                "subscription_status": "active",
                "subscription_start": subscription_start.isoformat(),
                "subscription_expiration": subscription_expiration.isoformat(),
                "grace_period_expiration": grace.isoformat(),
                "onboarding_completed": True,
            },
            on_conflict="user_id",
        )

    def set_free(self, user_id: str):
        """Free plan selection during onboarding — no payment involved."""
        upsert(
            "profiles",
            {
                "user_id": user_id,
                "tier": Tier.FREE.value,
                "subscription_status": "none",
                "onboarding_completed": True,
            },
            on_conflict="user_id",
        )

    def downgrade_to_free(self, user_id: str):
        upsert(
            "profiles",
            {"user_id": user_id, "tier": Tier.FREE.value, "subscription_status": "expired"},
            on_conflict="user_id",
        )

    def entitlements_for(self, user_id: str) -> Entitlements:
        return ENTITLEMENTS[self.get_tier(user_id)]