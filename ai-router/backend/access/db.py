"""
Thin Supabase (PostgREST) client for the server-side reads/writes that
must never be trusted to the frontend: subscription tier and image
upload quota. Uses the service role key, which bypasses every RLS
policy in the database — this module must only ever run in the
backend process, never be imported anywhere the frontend can reach.
"""
import requests
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

REQUEST_TIMEOUT = 15


def _headers(extra: dict | None = None) -> dict:
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


# Public alias — other modules (access/devices.py) need the same
# service-role headers for calls this module doesn't wrap (Admin API
# endpoints outside /rest/v1), and importing a leading-underscore name
# across modules is the kind of thing that quietly breaks later.
service_headers = _headers


def select(table: str, params: dict) -> list[dict]:
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers(),
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def upsert(table: str, row: dict, on_conflict: str) -> dict:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers({"Prefer": "resolution=merge-duplicates,return=representation"}),
        params={"on_conflict": on_conflict},
        json=row,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else row


def patch(table: str, params: dict, fields: dict) -> list[dict]:
    """PATCHes rows matching `params` (PostgREST filter syntax, e.g.
    {"id": "eq.<uuid>"}) and returns the changed rows — an empty list
    means the filter matched nothing, which callers can use to detect a
    no-op update (e.g. a status guard that didn't hold)."""
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers({"Prefer": "return=representation"}),
        params=params,
        json=fields,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def delete(table: str, params: dict) -> None:
    """Deletes rows matching `params` (PostgREST filter syntax). No
    return value — callers that need to know whether anything was
    actually deleted should select() first."""
    resp = requests.delete(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers({"Prefer": "return=minimal"}),
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


def insert(table: str, row: dict) -> dict:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_headers({"Prefer": "return=representation"}),
        json=row,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else row