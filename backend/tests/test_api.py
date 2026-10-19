import json

import pytest
from fastapi.testclient import TestClient

from app import main, orchestrator
from app.agents import AgentError
from app.schemas import ClaimExtraction, InputType, NormalizedInput
from test_orchestrator import extraction, make_claim, search


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "api.db"))
    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget: search)
    return TestClient(main.app)


def events_of(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def fake_pipeline(monkeypatch, claims=()):
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=list(claims), notes="n"))


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_stream_order_trace_verdict_done(client, monkeypatch):
    fake_pipeline(monkeypatch)
    events = events_of(client.post("/api/check", json={"kind": "text", "text": "hello"}))
    types = [e["type"] for e in events]
    assert types[-2:] == ["verdict", "done"]
    assert set(types[:-2]) == {"trace"}
    assert events[-1].keys() >= {"run_id", "cost_usd", "latency_ms", "tokens_in", "tokens_out", "cached"}


def test_bad_input_yields_error_then_done(client):
    events = events_of(client.post("/api/check", json={"kind": "text", "text": ""}))
    assert [e["type"] for e in events if e["type"] != "trace"] == ["error", "done"]
    assert [e for e in events if e["type"] == "error"][0]["code"] == "bad_input"


def test_unexpected_failure_is_internal_and_hides_details(client, monkeypatch):
    def boom(inp):
        raise AgentError("secret upstream detail")

    monkeypatch.setattr(orchestrator, "extract_claims", boom)
    events = events_of(client.post("/api/check", json={"kind": "text", "text": "hello"}))
    err = [e for e in events if e["type"] == "error"][0]
    assert err["code"] == "internal"
    assert "secret" not in err["message"]
    assert events[-1]["type"] == "done"


def test_run_is_stored_and_retrievable(client, monkeypatch):
    fake_pipeline(monkeypatch)
    events = events_of(client.post("/api/check", json={"kind": "text", "text": "hello"}))
    run_id = events[-1]["run_id"]
    stored = client.get(f"/api/runs/{run_id}").json()
    assert stored["run_id"] == run_id
    assert stored["events"][-1]["type"] == "done"
    assert stored["report"]["run_id"] == run_id


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/nope").status_code == 404


def test_cors_only_for_localhost_3000(client):
    ok = client.get("/health", headers={"Origin": "http://localhost:3000"})
    other = client.get("/health", headers={"Origin": "http://evil.test"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in other.headers
