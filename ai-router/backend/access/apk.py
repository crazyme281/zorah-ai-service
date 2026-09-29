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
# Specifically for the Storage upload call in upload_release() — a
# real APK is tens of MB, and the request has to survive both the
# browser->Render leg and the Render->Supabase leg before this even
# starts timing. 30s was almost certainly why uploads were silently
# failing (zero rows in apk_releases, zero objects in the bucket —
# confirmed against the live database before making this change).
UPLOAD_TIMEOUT = 180
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


class DeleteFailed(ApkError):
    """The current release couldn't be fully deleted — either Supabase
    Storage or the apk_releases row refused. Carries the upstream reason
    so the admin sees what actually went wrong instead of a bare 500."""


class StorageUploadFailed(ApkError):
    """Distinct from InvalidApkFile — this means the file itself was
    fine, but the network call to Supabase Storage didn't succeed
    (timeout, connection drop, Supabase-side error). Caught separately
    in api.py so the admin sees the real reason instead of a bare 500."""


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

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{APK_BUCKET}/{storage_path}",
            headers=service_headers({"Content-Type": "application/vnd.android.package-archive"}),
            data=data,
            timeout=UPLOAD_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise StorageUploadFailed(
            f"upload to Storage timed out after {UPLOAD_TIMEOUT}s — the file may be "
            "too large for the current connection, or Supabase Storage is slow to respond"
        )
    except requests.exceptions.RequestException as e:
        raise StorageUploadFailed(f"couldn't reach Supabase Storage: {e}")

    if resp.status_code >= 400:
        # The file was validated fine — this is Storage itself rejecting
        # or failing the upload. Surface its actual response rather than
        # a generic "upload failed", since that's the whole point of
        # this distinct exception type.
        raise StorageUploadFailed(
            f"Supabase Storage rejected the upload (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    # Belt-and-suspenders: confirm the object is actually listable in
    # Storage before writing anything to the database. A 2xx response
    # above should already mean it's there, but this is the one step
    # that turns "the API call didn't error" into "the file is
    # genuinely retrievable" — the actual requirement, not just the
    # absence of an exception.
    verify = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/list/{APK_BUCKET}",
        headers=service_headers(),
        json={"prefix": "releases/", "search": f"{meta['version_code']}-{original_filename}", "limit": 1},
        timeout=REQUEST_TIMEOUT,
    )
    if verify.status_code >= 400 or not verify.json():
        raise StorageUploadFailed(
            "upload appeared to succeed but the file isn't showing up in Storage yet — "
            "not saving this as the current release; try again"
        )

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

    # Bulk-delete endpoint (DELETE /object/{bucket} with a prefixes list)
    # rather than the single-object URL: it returns 200 with an empty
    # list when the object is already gone, whereas Storage reports a
    # missing object on the single-object route as HTTP 400 (with
    # statusCode "404" in the body), which the old status check treated
    # as a hard failure and surfaced as a 500.
    try:
        resp = requests.delete(
            f"{SUPABASE_URL}/storage/v1/object/{APK_BUCKET}",
            headers=service_headers(),
            json={"prefixes": [current["storage_path"]]},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        raise DeleteFailed(f"couldn't reach Supabase Storage to delete the file: {e}")

    if resp.status_code >= 400 and not _storage_says_not_found(resp):
        raise DeleteFailed(
            f"Supabase Storage rejected the delete (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    # The DB row is what determines "is there a current APK", so this is
    # the step that has to succeed for the delete to count.
    try:
        delete("apk_releases", {"id": f"eq.{current['id']}"})
    except requests.exceptions.RequestException as e:
        upstream = getattr(e, "response", None)
        reason = upstream.text[:300] if upstream is not None else str(e)
        raise DeleteFailed(f"file removed from Storage, but deleting the database row failed: {reason}")


def _storage_says_not_found(resp: "requests.Response") -> bool:
    if resp.status_code == 404:
        return True
    text = resp.text.lower()
    return '"statuscode":"404"' in text.replace(" ", "") or "not_found" in text or "not found" in text


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