"""
Image handling policy.

Two separate concerns kept deliberately separate:
1. Upload quota (how many images/day this tier allows) — enforced here,
   server-side, counting actual stored uploads, never trusting a
   frontend-supplied count.
2. Retention/availability (how long an image stays fetchable, and what
   to do when it's gone) — the AI must say plainly it can't access an
   image rather than ever pretending to see one that isn't there.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from access.tiers import SubscriptionStore

SERVER_RETENTION = timedelta(days=3)


class ImageQuotaExceeded(Exception):
    pass


@dataclass
class StoredImage:
    image_id: str
    user_id: str
    uploaded_at: datetime
    still_on_device: bool = True  # best-effort signal from the client, not trusted for quota


class ImageStore:
    """
    Tracks uploads for quota purposes and models the resync behavior:
    the server only ever holds an image for SERVER_RETENTION. Anything
    older is treated as gone from the server even if the on-device
    fields say otherwise — resync() is what's supposed to refill it.
    """

    def __init__(self, subscriptions: SubscriptionStore):
        self.subscriptions = subscriptions
        self._images: dict[str, StoredImage] = {}
        # user_id -> list of upload timestamps today, for quota counting
        self._uploads_today: dict[str, list[datetime]] = {}

    def _count_today(self, user_id: str, now: datetime) -> int:
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stamps = self._uploads_today.get(user_id, [])
        return sum(1 for t in stamps if t >= window_start)

    def record_upload(self, user_id: str, image_id: str, now: datetime = None) -> StoredImage:
        now = now or datetime.now(timezone.utc)
        limit = self.subscriptions.entitlements_for(user_id).daily_image_uploads

        # Enforced here, against real recorded uploads — this is the
        # server-side check the spec requires. A frontend counter is
        # never consulted.
        if self._count_today(user_id, now) >= limit:
            raise ImageQuotaExceeded(
                f"user {user_id} has reached their daily limit of {limit} image uploads"
            )

        self._uploads_today.setdefault(user_id, []).append(now)
        record = StoredImage(image_id=image_id, user_id=user_id, uploaded_at=now)
        self._images[image_id] = record
        return record

    def is_available_on_server(self, image_id: str, now: datetime = None) -> bool:
        now = now or datetime.now(timezone.utc)
        record = self._images.get(image_id)
        if record is None:
            return False
        return (now - record.uploaded_at) <= SERVER_RETENTION

    def resync_from_device(self, image_id: str, device_has_it: bool, now: datetime = None) -> bool:
        """
        Called when an old conversation references an image that's aged
        out of server retention. If the device still has it, refresh the
        server copy's clock. If not, the caller must be told plainly —
        see `access_result` below, which is what the AI-facing code
        should actually check before responding.
        """
        now = now or datetime.now(timezone.utc)
        record = self._images.get(image_id)
        if record is None:
            return False
        record.still_on_device = device_has_it
        if device_has_it:
            record.uploaded_at = now  # resynced, retention window restarts
            return True
        return False

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
