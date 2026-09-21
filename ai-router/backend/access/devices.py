"""
Device linking — lets an already-authenticated website session hand the
mobile app a real login without the user typing a password into the app.

The mechanism is a short-lived, single-use pairing code (like a TV app's
"enter this code on your phone" flow, just reversed): the website asks for
a code, shows it, the user types it into the mobile app, and the backend
exchanges a valid code for a genuine Supabase session — minted through
Supabase's own official admin flow, not a hand-rolled token.

Nothing here trusts a bare user_id from a request body. Every endpoint
that acts on an account requires a real, freshly verified Supabase access
token (see require_user() in api.py) — the one exception is consuming a
pairing code, which is deliberately reachable without a session, since
that's the whole point of the flow. Its safety comes from the code being
short (8 chars), random (log2(32^8) ≈ 40 bits), single-use, and expiring
in 2 minutes, not from any caller identity check.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import requests

from access.db import select, insert, upsert, patch, service_headers
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

REQUEST_TIMEOUT = 15

# 2 minutes is generous for "read this code off one screen, type it into
# another" and short enough that a leaked/observed code is worthless by
# the time anyone could act on it.
CODE_TTL_SECONDS = 120

# Excludes visually ambiguous characters (0/O, 1/I/L) — this code gets
# hand-typed from one device to another.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


class DeviceLinkError(Exception):
    """Base for every error this module raises — api.py maps these to
    4xx responses without leaking internals."""


class InvalidOrExpiredCode(DeviceLinkError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


# --------------------------------------------------------------- pairing --

def start_link(user_id: str) -> dict:
    """
    Website side: mint a fresh code for the logged-in user. Old pending
    codes for this user are left to simply expire — no need to invalidate
    them, since only one can ever be successfully consumed regardless.
    """
    code = _generate_code()
    expires_at = _now() + timedelta(seconds=CODE_TTL_SECONDS)

    insert(
        "device_link_tokens",
        {
            "user_id": user_id,
            "code_hash": _hash_code(code),
            "status": "pending",
            "expires_at": expires_at.isoformat(),
        },
    )

    return {"code": code, "expires_in": CODE_TTL_SECONDS}


def consume_link(code: str, device_installation_id: str, platform: str, push_token: str | None) -> dict:
    """
    Mobile side: exchange a valid code for a real Supabase session.

    Raises InvalidOrExpiredCode for anything wrong with the code at all
    (not found, already used, expired) — deliberately one error message
    for all three, so a guesser learns nothing about which codes are
    "closer" to valid.
    """
    code = (code or "").strip().upper()
    if len(code) != CODE_LENGTH:
        raise InvalidOrExpiredCode("invalid code")

    rows = select(
        "device_link_tokens",
        {
            "code_hash": f"eq.{_hash_code(code)}",
            "status": "eq.pending",
            "select": "*",
            "limit": "1",
        },
    )
    if not rows:
        raise InvalidOrExpiredCode("invalid or already-used code")

    token = rows[0]
    expires_at = datetime.fromisoformat(token["expires_at"].replace("Z", "+00:00"))
    if _now() > expires_at:
        # Mark it explicitly rather than leaving it "pending" forever —
        # keeps the table honest for anyone reading it directly.
        _patch_token(token["id"], {"status": "expired"})
        raise InvalidOrExpiredCode("code has expired")

    # Consume it before doing anything else: if two requests race on the
    # same code, only the first to win this update should succeed. The
    # WHERE status=eq.pending guard makes the second request affect zero
    # rows, which we detect and reject.
    updated = _patch_token(
        token["id"],
        {
            "status": "consumed",
            "consumed_at": _now().isoformat(),
            "consumed_by_device": device_installation_id,
        },
        guard_status="pending",
    )
    if not updated:
        raise InvalidOrExpiredCode("code was just used by another request")

    user_id = token["user_id"]
    register_device(user_id, device_installation_id, platform, push_token)
    session = _mint_session_for_user(user_id)
    return session


# --------------------------------------------------------------- devices --

def register_device(user_id: str, device_installation_id: str, platform: str, push_token: str | None) -> dict:
    """
    Upserts the device row. Called both from consume_link() and directly
    by an already-authenticated client after a normal Google/password
    login, so every login path — not just the pairing-code one — ends up
    represented in user_devices.
    """
    row = {
        "user_id": user_id,
        "device_installation_id": device_installation_id,
        "platform": platform,
        "last_seen": _now().isoformat(),
        "linked_at": _now().isoformat(),
        "revoked_at": None,
    }
    if push_token:
        row["push_token"] = push_token
    return upsert("user_devices", row, on_conflict="user_id,device_installation_id")


def touch_device(user_id: str, device_installation_id: str) -> None:
    """Cheap last_seen bump — called on app foreground, not every request."""
    upsert(
        "user_devices",
        {
            "user_id": user_id,
            "device_installation_id": device_installation_id,
            "last_seen": _now().isoformat(),
        },
        on_conflict="user_id,device_installation_id",
    )


def list_devices(user_id: str) -> list[dict]:
    return select(
        "user_devices",
        {"user_id": f"eq.{user_id}", "select": "*", "order": "last_seen.desc"},
    )


def revoke_device(user_id: str, device_id: str) -> None:
    """
    Marks the device revoked. This does NOT instantly kill a live session
    on that device — Supabase Auth has no per-device token revocation, only
    a whole-account "sign out everywhere." Enforcement is soft: the app
    checks its own device's status on each foreground (see /devices/self)
    and signs itself out locally the moment it sees revoked_at set. Say
    this plainly rather than imply instant revocation the platform can't
    actually do.
    """
    patch(
        "user_devices",
        {"id": f"eq.{device_id}", "user_id": f"eq.{user_id}"},
        {"revoked_at": _now().isoformat()},
    )


def device_status(user_id: str, device_installation_id: str) -> dict | None:
    rows = select(
        "user_devices",
        {
            "user_id": f"eq.{user_id}",
            "device_installation_id": f"eq.{device_installation_id}",
            "select": "revoked_at,last_seen",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def _patch_token(token_id: str, fields: dict, guard_status: str | None = None) -> bool:
    """PATCHes device_link_tokens and returns whether any row actually
    changed — used to detect the consume-race case above."""
    params = {"id": f"eq.{token_id}"}
    if guard_status:
        params["status"] = f"eq.{guard_status}"
    return len(patch("device_link_tokens", params, fields)) > 0


# --------------------------------------------------- Supabase admin auth --

def _mint_session_for_user(user_id: str) -> dict:
    """
    Turns a verified user_id into a real Supabase session using only
    Supabase's own official Admin API — no custom JWT signing lives here.

    generate_link (type=magiclink) produces a one-time token_hash tied to
    the user's email; immediately verifying that token_hash exchanges it
    for an actual access_token/refresh_token pair, exactly as if the user
    had clicked a real magic-link email. The email never gets sent — we
    only use the token_hash it would have contained.
    """
    email = _get_user_email(user_id)

    gen = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/generate_link",
        headers=service_headers(),
        json={"type": "magiclink", "email": email},
        timeout=REQUEST_TIMEOUT,
    )
    gen.raise_for_status()
    token_hash = gen.json()["properties"]["hashed_token"]

    verify = requests.post(
        f"{SUPABASE_URL}/auth/v1/verify",
        headers={"apikey": SUPABASE_SERVICE_ROLE_KEY, "Content-Type": "application/json"},
        json={"type": "magiclink", "token_hash": token_hash},
        timeout=REQUEST_TIMEOUT,
    )
    verify.raise_for_status()
    data = verify.json()

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expires_in", 3600),
        "user_id": user_id,
    }


def _get_user_email(user_id: str) -> str:
    resp = requests.get(
        f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    email = resp.json().get("email")
    if not email:
        raise DeviceLinkError("account has no email on file")
    return email