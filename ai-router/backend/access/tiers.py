"""
FREE vs PRO entitlements.

The one rule that matters here: subscription state is looked up from
wherever `get_tier` actually queries (a DB in production), never taken
as a claim passed in from the client. Every call site below takes a
user_id and resolves the tier itself — there is deliberately no
"trust_frontend_tier" parameter anywhere in this file. If you're
tempted to add one for convenience, don't; that's exactly the bug
rule #3 in the spec exists to prevent.
"""
from dataclasses import dataclass
from enum import Enum


class Tier(str, Enum):
    FREE = "FREE"
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
        daily_image_uploads=7,
        can_generate_images=False,
        can_use_groq_fast_lane=False,
        can_generate_pptx=False,
        can_generate_pdf=False,
        can_generate_docx=False,
        higher_reasoning=False,
    ),
    Tier.PRO: Entitlements(
        daily_image_uploads=12,
        can_generate_images=True,
        can_use_groq_fast_lane=True,
        can_generate_pptx=True,
        can_generate_pdf=True,
        can_generate_docx=True,
        higher_reasoning=True,
    ),
}


class SubscriptionStore:
    """
    Stand-in for the real database lookup. In production this is a
    query against your users table, not a dict — the interface below
    is what the rest of the app should depend on, so swapping the
    in-memory dict for a real DB call is a one-file change.
    """

    def __init__(self):
        self._tiers: dict[str, Tier] = {}

    def get_tier(self, user_id: str) -> Tier:
        return self._tiers.get(user_id, Tier.FREE)

    def set_tier(self, user_id: str, tier: Tier):
        """Only ever called after a verified payment — see access/payments.py."""
        self._tiers[user_id] = tier

    def entitlements_for(self, user_id: str) -> Entitlements:
        return ENTITLEMENTS[self.get_tier(user_id)]
