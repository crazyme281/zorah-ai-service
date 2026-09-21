"""
APK release management for the "Get App" / auto-update system.

Nothing here trusts an admin-typed version number. Every uploaded file is
actually opened and its real compiled AndroidManifest.xml is read (via
pyaxmlparser) to pull the true package name, versionName and versionCode
— a file that isn't a genuine, parseable APK for this app's package id is
rejected before it ever reaches storage. That's the "don't trust the
client" principle applied to the admin side too, not just normal users.
"""

from datetime import datetime, timedelta, timezone

import requests
from pyaxmlparser import APK

from access.db import select, insert, delete, service_headers
from config import SUPABASE_URL

REQUEST_TIMEOUT = 30
APK_BUCKET = "apk-releases"
EXPECTED_PACKAGE = "ai.zorah.app"

# Rolling windows rather than a fixed weekly reset (e.g. "resets Monday
# 00:00") — counting rows from the last 7 days has no reset-boundary edge
# case and self-corrects if the backend is ever down for a stretch.
PROMO_WEEKLY_CAP = 3
OUTDATED_WEEKLY_CAP = 2
POPUP_WINDOW_DAYS = 7

MAX_APK_BYTES = 250 * 1024 * 1024  # 250MB — generous for a Capacitor app, not unbounded


class ApkError(Exception):
    """Base for every error this module raises — api.py maps these to
    specific 4xx responses."""


class InvalidApkFile(ApkError):
    pass


class ApkAlreadyExists(ApkError):
    pass


class NoCurrentApk(ApkError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- parsing --

def parse_apk(data: bytes) -> dict:
    """Opens the APK's real compiled manifest and pulls real values.
    Raises InvalidApkFile with a specific, safe-to-show-the-admin reason
    for anything wrong — corrupt zip, wrong package, unreadable manifest."""
    if len(data) > MAX_APK_BYTES:
        raise InvalidApkFile(f"file is larger than the {MAX_APK_BYTES // (1024*1024)}MB limit")

    # APKs are ZIP files — PK\x03\x04 is the local file header signature.
    # Rejecting non-ZIP content before handing it to the parser turns a
    # confusing parser stack trace into a clear, immediate error.
    if data[:4] != b"PK\x03\x04":
        raise InvalidApkFile("not a valid APK — file doesn't look like a ZIP archive")

    try:
        apk = APK(data, raw=True, testzip=True)
    except Exception as e:
        raise InvalidApkFile(f"couldn't read this as an APK: {e}")

    if not apk.package:
        raise InvalidApkFile("no package name found — not a valid Android app")

    if apk.package != EXPECTED_PACKAGE:
        raise InvalidApkFile(
            f"this APK is for package '{apk.package}', expected '{EXPECTED_PACKAGE}'"
        )

    version_code = apk.get_androidversion_code()
    version_name = apk.get_androidversion_name()
    if not version_code or not str(version_code).isdigit():
        raise InvalidApkFile("couldn't read a version code from this APK's manifest")

    return {
        "package": apk.package,
        "version": version_name or "0",
        "version_code": int(version_code),
    }


# ------------------------------------------------------------ management --

def get_current() -> dict | None:
    rows = select("apk_releases", {"is_current": "eq.true", "select": "*", "limit": "1"})
    return rows[0] if rows else None


def upload_release(data: bytes, original_filename: str, uploaded_by: str) -> dict:
    """The workflow the spec requires — delete-before-upload — is
    enforced here, not just in the UI: a second upload while one is
    already current is rejected outright."""
    if get_current() is not None:
        raise ApkAlreadyExists("delete the current APK before uploading a new one")

    meta = parse_apk(data)
    storage_path = f"releases/{meta['version_code']}-{original_filename}"

    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{APK_BUCKET}/{storage_path}",
        headers=service_headers({"Content-Type": "application/vnd.android.package-archive"}),
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    return insert(
        "apk_releases",
        {
            "version": meta["version"],
            "version_code": meta["version_code"],
            "package_name": meta["package"],
            "file_name": original_filename,
            "storage_path": storage_path,
            "file_size": len(data),
            "uploaded_by": uploaded_by,
            "is_current": True,
        },
    )


def delete_current() -> None:
    """Deletes both the storage object and the DB row — a real delete,
    not a soft-flip of is_current, matching the spec's "old APK must be
    deleted" wording exactly."""
    current = get_current()
    if current is None:
        raise NoCurrentApk("no current APK to delete")

    resp = requests.delete(
        f"{SUPABASE_URL}/storage/v1/object/{APK_BUCKET}/{current['storage_path']}",
        headers=service_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    # A 404 here just means the storage object was already gone somehow —
    # the DB row is still the thing that determines "is there a current
    # APK," so that's what actually has to succeed.
    if resp.status_code not in (200, 404):
        resp.raise_for_status()

    delete("apk_releases", {"id": f"eq.{current['id']}"})


def signed_download_url(expires_in: int = 300) -> dict:
    """Short-lived signed URL rather than a public bucket — so a stale
    bookmarked link can't fetch an APK that's since been deleted, and
    nothing about the bucket's contents is guessable/enumerable."""
    current = get_current()
    if current is None:
        raise NoCurrentApk("no APK is currently available")

    resp = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/sign/{APK_BUCKET}/{current['storage_path']}",
        headers=service_headers(),
        json={"expiresIn": expires_in},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    signed_path = resp.json()["signedURL"]

    return {
        "url": f"{SUPABASE_URL}/storage/v1{signed_path}",
        "expires_in": expires_in,
        "version": current["version"],
        "version_code": current["version_code"],
        "file_name": current["file_name"],
        "file_size": current["file_size"],
    }


# ----------------------------------------------------------- popup state --

def should_show_popup(user_id: str, popup_type: str) -> bool:
    since = (_now() - timedelta(days=POPUP_WINDOW_DAYS)).isoformat()
    rows = select(
        "apk_popup_events",
        {
            "user_id": f"eq.{user_id}",
            "popup_type": f"eq.{popup_type}",
            "created_at": f"gte.{since}",
            "select": "id",
        },
    )
    cap = PROMO_WEEKLY_CAP if popup_type == "promo" else OUTDATED_WEEKLY_CAP
    return len(rows) < cap


def mark_popup_shown(user_id: str, popup_type: str) -> None:
    insert("apk_popup_events", {"user_id": user_id, "popup_type": popup_type})