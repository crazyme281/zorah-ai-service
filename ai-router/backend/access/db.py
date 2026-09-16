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