"""call_worker waits for a sleeping worker and retries 'busy' answers."""
import pytest

from access import codefix_pipeline as cp


class R:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._b, self.headers, self.text = status, body or {}, headers or {}, text

    def json(self):
        return self._b


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("print(1)")
    monkeypatch.setattr(cp, "WORKER_URL", "http://worker")
    monkeypatch.setattr(cp, "WORKER_SHARED_SECRET", "s")
    sleeps = []
    monkeypatch.setattr(cp.time, "sleep", lambda s: sleeps.append(s))
    return tmp_path, sleeps


OK = {"results": [{"command": "x", "exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}]}


def test_waits_for_health_then_runs(env, monkeypatch):
    root, sleeps = env
    health = iter([R(429), R(503), R(200)])
    monkeypatch.setattr(cp.requests, "get", lambda url, **kw: next(health))
    monkeypatch.setattr(cp.requests, "post", lambda url, **kw: R(200, OK))
    assert cp.call_worker(root, ["x"]) == OK["results"]
    assert len(sleeps) == 2                                   # slept twice while it was waking


def test_retries_429_and_honours_retry_after(env, monkeypatch):
    root, sleeps = env
    monkeypatch.setattr(cp.requests, "get", lambda url, **kw: R(200))
    seq = iter([R(429, headers={"Retry-After": "7"}), R(429), R(200, OK)])
    monkeypatch.setattr(cp.requests, "post", lambda url, **kw: next(seq))
    assert cp.call_worker(root, ["x"]) == OK["results"]
    assert sleeps[0] == 7.0 and len(sleeps) == 2


def test_gives_up_with_a_clear_message(env, monkeypatch):
    root, _ = env
    monkeypatch.setattr(cp.requests, "get", lambda url, **kw: R(200))
    monkeypatch.setattr(cp.requests, "post", lambda url, **kw: R(429))
    with pytest.raises(cp.PipelineError, match="HTTP 429 .*after 5 tries"):
        cp.call_worker(root, ["x"])


def test_wrong_secret_and_other_errors_fail_fast(env, monkeypatch):
    root, sleeps = env
    monkeypatch.setattr(cp.requests, "get", lambda url, **kw: R(200))
    monkeypatch.setattr(cp.requests, "post", lambda url, **kw: R(401))
    with pytest.raises(cp.PipelineError, match="shared secret"):
        cp.call_worker(root, ["x"])
    monkeypatch.setattr(cp.requests, "post", lambda url, **kw: R(400, text="bad zip"))
    with pytest.raises(cp.PipelineError, match="HTTP 400: bad zip"):
        cp.call_worker(root, ["x"])
    assert sleeps == []                                       # no pointless waiting


def test_unreachable_worker_is_retried(env, monkeypatch):
    root, _ = env
    monkeypatch.setattr(cp.requests, "get", lambda url, **kw: R(200))
    seq = iter([cp.requests.ConnectionError("down"), R(200, OK)])

    def post(url, **kw):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(cp.requests, "post", post)
    assert cp.call_worker(root, ["x"]) == OK["results"]