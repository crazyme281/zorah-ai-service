import json
from fastapi.testclient import TestClient
import api


class F:
    def chat(self, m, **k):
        return "reply from provider"


def client():
    api.router.providers = {n: F() for n in ["claude", "gemini", "zai", "groq", "cohere"]}
    return TestClient(api.app)


def test_topics_endpoint():
    r = client().get("/learning/topics")
    assert r.status_code == 200 and len(r.json()["topics"]) == 4


def test_model_info_reports_metrics_not_secrets():
    r = client().get("/learning/model-info").json()
    assert r["meta"]["test"]["answered_wrongly"] == 0
    blob = json.dumps(r)
    assert '"idf"' not in blob and '"examples"' not in blob and "answers" not in r["meta"]


def test_chat_uses_learned_when_sure_and_provider_when_not():
    c = client()
    sure = c.post("/chat", json={"messages": [{"role": "user", "content": "what is overfitting"}], "session_id": "t1"}).json()
    assert "memoris" in sure["reply"].lower() and sure["model_label"] == "lite1.2"
    unsure = c.post("/chat", json={"messages": [{"role": "user", "content": "write a poem about the sea"}], "session_id": "t1"}).json()
    assert unsure["reply"] == "reply from provider"


def test_stream_works_for_both_paths():
    c = client()
    for q, needle in (("what is a decision tree", "yes/no questions"), ("recommend a laptop", "reply from provider")):
        r = c.post("/chat/stream", json={"messages": [{"role": "user", "content": q}], "session_id": "t2"})
        assert r.status_code == 200 and needle in r.text.lower()