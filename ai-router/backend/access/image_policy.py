"""
Image handling policy.

Two separate concerns kept deliberately separate:
1. Upload quota (how many images/day this tier allows) — enforced by
   counting real rows in Supabase's `image_uploads` table, never a
   frontend-supplied count. Checked the moment the backend authorizes
   an upload (POST /images/authorize), called from the frontend's
   prepareImage() *before* the file is compressed or sent to Storage —
   so a rejected upload never touches Storage or counts against
   anything.
2. Retention/availability (how long an image stays fetchable, and what
   to do when it's gone) — the AI must say plainly it can't access an
   image rather than ever pretending to see one that isn't there.

Both are backed by the same `image_uploads` table (see the migration
that ships with this file) so neither resets when the backend
restarts or scales to more than one instance — the original version of
this file tracked both in an in-memory dict, which loses everything on
every Render redeploy.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from access.db import select, insert, upsert
from access.tiers import SubscriptionStore

SERVER_RETENTION = timedelta(days=3)


class ImageQuotaExceeded(Exception):
    def __init__(self, limit: int, tier: str):
        self.limit = limit
        self.tier = tier
        super().__init__(f"daily limit of {limit} image uploads reached on the {tier} plan")


class ImageStore:
    def __init__(self, subscriptions: SubscriptionStore):
        self.subscriptions = subscriptions

    # -- Quota -----------------------------------------------------------

    def _count_today(self, user_id: str, now: datetime) -> int:
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = select(
            "image_uploads",
            {
                "user_id": f"eq.{user_id}",
                "uploaded_at": f"gte.{start_of_day.isoformat()}",
                "select": "id",
            },
        )
        return len(rows)

    def remaining_today(self, user_id: str, now: datetime = None) -> dict:
        now = now or datetime.now(timezone.utc)
        tier = self.subscriptions.get_tier(user_id)
        limit = self.subscriptions.entitlements_for(user_id).daily_image_uploads
        used = self._count_today(user_id, now)
        return {"tier": tier.value, "limit": limit, "used": used, "remaining": max(0, limit - used)}

    def record_upload(self, user_id: str, image_id: str, now: datetime = None) -> dict:
        """
        Checks quota, then records this specific upload — both the
        quota-counting row AND the retention clock for `image_id` start
        here. Raises ImageQuotaExceeded if the user is already at their
        tier's daily limit. Call this BEFORE the image is
        compressed/uploaded to Storage, not after.
        """
        now = now or datetime.now(timezone.utc)
        status = self.remaining_today(user_id, now)
        if status["remaining"] <= 0:
            raise ImageQuotaExceeded(status["limit"], status["tier"])

        insert(
            "image_uploads",
            {
                "user_id": user_id,
                "image_id": image_id,
                "uploaded_at": now.isoformat(),
                "last_seen_at": now.isoformat(),
            },
        )
        return self.remaining_today(user_id, now)

    # -- Retention / availability -----------------------------------------

    def is_available_on_server(self, image_id: str, now: datetime = None) -> bool:
        now = now or datetime.now(timezone.utc)
        rows = select("image_uploads", {"image_id": f"eq.{image_id}", "select": "last_seen_at"})
        if not rows:
            return False
        last_seen = datetime.fromisoformat(rows[0]["last_seen_at"].replace("Z", "+00:00"))
        return (now - last_seen) <= SERVER_RETENTION

    def resync_from_device(self, image_id: str, device_has_it: bool, now: datetime = None) -> bool:
        """
        Called when an old conversation references an image that's aged
        out of server retention. If the device still has it, refresh the
        server copy's clock so it's available again. If not, the caller
        must be told plainly — see `access_result` below, which is what
        the AI-facing code should actually check before responding.
        """
        if not device_has_it:
            return False
        now = now or datetime.now(timezone.utc)
        upsert(
            "image_uploads",
            {"image_id": image_id, "last_seen_at": now.isoformat()},
            on_conflict="image_id",
        )
        return True

    def access_result(self, image_id: str, now: datetime = None) -> dict:
        """
        The single function the AI layer should call before referencing
        an image. Never returns a "pretend it's there" state — only
        "available" or "unavailable", so the caller has no path to
        claim it can see something it can't.
        """
        available = self.is_available_on_server(image_id, now)
        return {
            "image_id": image_id,
            "available": available,
            "message": None if available else (
                "I can't access that image anymore — it's aged out of temporary "
                "storage and isn't on the device to resync from. I can't describe "
                "or reference it."
            ),
        }