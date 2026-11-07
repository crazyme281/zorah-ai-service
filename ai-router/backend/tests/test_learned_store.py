"""Learned chat knowledge is saved to Supabase (survives redeploys), kept after
the first vetted ask, and restored into the model after a restart."""
import json

import pytest

import learned
from learned import chat_learning as cl
from learned import supabase_store as remote

Q = "what is the capital of France"
A = "Paris is the capital and largest city of France, on the Seine."


class FakeSupabase:
    """Stands in for the PostgREST table so no network is needed."""
    def __init__(self):
        self.rows = {}
        self.fail = False

    def get(self, url, headers=None, params=None, timeout=None):
        if self.fail:
            raise RuntimeError("offline")
        return self._resp(list(self.rows.values()))

    def post(self, url, headers=None, params=None, json=None, timeout=None):
        if self.fail:
            raise RuntimeError("offline")
        for r in json:
            self.rows[r["id"]] = r
        return self._resp([])

    @staticmethod
    def _resp(body):
        class R:
            def raise_for_status(self): pass
            def json(self): return body
        return R()


@pytest.fixture
def sb(tmp_path, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(remote, "enabled", lambda: True)
    monkeypatch.setattr(remote.requests, "get", fake.get)
    monkeypatch.setattr(remote.requests, "post", fake.post)
    monkeypatch.setattr(cl, "STORE_PATH", str(tmp_path / "chat.json"))
    monkeypatch.setattr(cl, "ENABLED", True)
    monkeypatch.setattr(cl, "MIN_ASKS", 1)
    monkeypatch.setitem(cl._remote, "cache", None)
    monkeypatch.setitem(cl._remote, "pusher", remote.Pusher())
    return fake


def test_default_is_to_keep_a_vetted_answer_after_the_first_ask():
    assert cl.MIN_ASKS == 1


def test_first_ask_is_saved_to_supabase(sb):
    assert cl.record(Q, A, "claude", "s1") == "ready"           # queued for training after ONE ask
    cl._remote["pusher"].flush()
    assert len(sb.rows) == 1
    row = next(iter(sb.rows.values()))
    assert row["answer"] == A and row["status"] == "queued" and row["source"] == "provider_generated"
    assert "s1" not in json.dumps(row)                           # only hashed sessions are stored


def test_knowledge_comes_back_after_a_redeploy(sb, tmp_path, monkeypatch):
    cl.record(Q, A, "claude", "s1")
    cl._remote["pusher"].flush()
    # redeploy: local disk wiped, process memory gone - only Supabase remains
    monkeypatch.setattr(cl, "STORE_PATH", str(tmp_path / "fresh" / "chat.json"))
    monkeypatch.setitem(cl._remote, "cache", None)
    monkeypatch.setitem(cl._remote, "pusher", remote.Pusher())
    assert [e["answer"] for e in cl.entries_for_training()] == [A]


def test_changes_are_pushed_and_unchanged_entries_are_not_resent(sb):
    cl.record(Q, A, "claude", "s1")
    cl._remote["pusher"].flush()
    entry_id = next(iter(sb.rows))
    cl.mark({entry_id}, {})                                      # now active
    cl._remote["pusher"].flush()
    assert sb.rows[entry_id]["status"] == "active"
    sb.rows.clear()
    cl._save(cl._load())                                         # nothing changed
    cl._remote["pusher"].flush()
    assert sb.rows == {}


def test_supabase_outage_falls_back_to_the_file_and_retries(sb):
    sb.fail = True
    assert cl.record(Q, A, "claude", "s1") in ("recorded", "ready")
    cl._remote["pusher"].flush()
    assert sb.rows == {} and cl.provenance_counts()["total"] == 1   # still learned locally
    sb.fail = False
    cl.record("why is the sky blue?", "Air scatters blue light more strongly than red light.", "groq", "s2")
    cl._remote["pusher"].flush()
    assert len(sb.rows) == 2                                     # the earlier one was retried too


def test_existing_local_knowledge_is_uploaded_on_first_connect(sb, tmp_path):
    json.dump({"entries": [{"id": "abc", "questions": [Q], "answer": A, "provider": "claude", "source": "provider_generated",
                            "sessions": ["h"], "status": "active", "first_seen": 1, "last_seen": 1}]},
              open(cl.STORE_PATH, "w"))
    cl._load()
    cl._remote["pusher"].flush()
    assert "abc" in sb.rows


def test_summary_reports_the_storage_backend(sb):
    assert cl.summary()["storage"] == "supabase"


def test_boot_retrains_when_the_store_has_knowledge_the_model_lacks(sb, tmp_path, monkeypatch):
    monkeypatch.setattr(learned, "ARTIFACT", str(tmp_path / "model.json"))
    monkeypatch.setitem(learned._state, "model", None)
    monkeypatch.setitem(learned._state, "meta", None)
    learned.sleep_cycle(by="test")                               # artifact with no chat knowledge
    cl.record(Q, A, "claude", "s1")
    monkeypatch.setitem(learned._state, "model", None)           # simulated restart
    monkeypatch.setitem(learned._state, "meta", None)
    trained = []
    real = learned._train
    monkeypatch.setattr(learned, "_train", lambda *a, **k: trained.append(1) or real(*a, **k))
    learned._load()
    assert trained, "expected a retrain because the store has an entry the artifact was not trained with"