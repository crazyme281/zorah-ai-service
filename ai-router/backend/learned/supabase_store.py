"""
Supabase persistence for the knowledge the learned model picks up from chat.

Render's disk is wiped on every deploy, so a JSON file cannot remember what
the model learned. This keeps the same entries in the `learned_chat_entries`
table (service-role access only; see the migration) and mirrors them to the
local file as a fallback.

Design:
  * entries are read from Supabase once per process (then served from memory),
    so a chat turn never waits on the network to read;
  * changed entries are written by a background thread, so a chat turn never
    waits on the network to write either;
  * if Supabase is unreachable or the table is missing, learning keeps working
    from the local file and the failed writes are retried on the next change.
"""
import json
import logging
import os
import threading

import requests

from config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

logger = logging.getLogger("ai_router.learned.store")
TABLE = "learned_chat_entries"
_FIELDS = ("id", "questions", "answer", "provider", "source", "sessions", "status", "reason", "first_seen", "last_seen")


def enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY) and os.getenv("LEARN_STORE", "supabase").lower() != "file"


def _headers(extra=None):
    h = {"apikey": SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
         "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def _row(entry: dict) -> dict:
    return {k: entry.get(k) for k in _FIELDS if entry.get(k) is not None}


def fetch_all() -> list[dict] | None:
    """Every stored entry, or None if Supabase could not be reached."""
    try:
        resp = requests.get(f"{SUPABASE_URL}/rest/v1/{TABLE}", headers=_headers(),
                            params={"select": ",".join(_FIELDS), "limit": "2000"}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("learned: could not read %s from Supabase (%s); using the local file", TABLE, e)
        return None


class Pusher:
    """Writes changed entries to Supabase on a background thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sent: dict[str, str] = {}     # id -> snapshot already stored remotely
        self._pending: dict[str, dict] = {}
        self._thread: threading.Thread | None = None

    def mark_remote(self, entries: list[dict]):
        with self._lock:
            self._sent = {e["id"]: json.dumps(_row(e), sort_keys=True) for e in entries}

    def push(self, entries: list[dict]):
        with self._lock:
            for e in entries:
                if self._sent.get(e["id"]) != json.dumps(_row(e), sort_keys=True):
                    self._pending[e["id"]] = _row(e)
            if self._pending and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, daemon=True, name="learned-store")
                self._thread.start()

    def flush(self, timeout: float = 10.0):
        t = self._thread
        if t is not None:
            t.join(timeout)

    def _run(self):
        while True:
            with self._lock:
                batch = list(self._pending.values())
                self._pending = {}
            if not batch:
                return
            try:
                resp = requests.post(
                    f"{SUPABASE_URL}/rest/v1/{TABLE}", headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                    params={"on_conflict": "id"}, json=batch, timeout=20)
                resp.raise_for_status()
                with self._lock:
                    for r in batch:
                        self._sent[r["id"]] = json.dumps(r, sort_keys=True)
            except Exception as e:
                logger.warning("learned: could not save %d entries to Supabase (%s); will retry on the next change", len(batch), e)
                with self._lock:  # keep them for the next push, unless newer data replaced them
                    for r in batch:
                        self._pending.setdefault(r["id"], r)
                return