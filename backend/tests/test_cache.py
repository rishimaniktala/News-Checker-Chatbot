import json

import pytest
from fastapi.testclient import TestClient

from app import cache, main, orchestrator, store
from app.schemas import ClaimExtraction
from test_orchestrator import search

BODY = {"kind": "text", "text": "Sweden joined NATO in 2024."}


@pytest.fixture
def client(monkeypatch):
    calls = []

    def extract(inp):
        calls.append(inp.text)
        return ClaimExtraction(claims=[], notes="n")

    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget, **kw: search)
    monkeypatch.setattr(orchestrator, "extract_claims", extract)
    c = TestClient(main.app)
    c.calls = calls
    return c


def post(client, body=BODY):
    resp = client.post("/api/check", json=body)
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def test_second_identical_text_is_served_from_cache(client):
    first = post(client)
    second = post(client)
    assert len(client.calls) == 1
    done = second[-1]
    assert done["cached"] is True and done["cost_usd"] == 0 and done["tokens_in"] == 0
    assert any(e.get("message") == "Served from cache" for e in second)
    verdict = [e for e in second if e["type"] == "verdict"][0]["report"]
    assert verdict["run_id"] == done["run_id"] != first[-1]["run_id"]
    assert verdict["answer"] == [e for e in first if e["type"] == "verdict"][0]["report"]["answer"]


def test_spacing_does_not_change_the_key_but_case_does(client):
    post(client)
    post(client, {"kind": "text", "text": "  Sweden joined   NATO in 2024. "})
    assert len(client.calls) == 1
    post(client, {"kind": "text", "text": "sweden joined nato in 2024."})
    assert len(client.calls) == 2


def test_key_changes_with_model_prompt_version_and_sources(monkeypatch):
    base = cache.key_for("x")
    monkeypatch.setenv("MODEL_PRIMARY", "other")
    assert cache.key_for("x") != base
    monkeypatch.delenv("MODEL_PRIMARY")
    monkeypatch.setenv("SOURCES", "guardian")
    assert cache.key_for("x") != base
    monkeypatch.delenv("SOURCES")
    monkeypatch.setattr("app.prompts.PROMPT_VERSION", "v-other", raising=False)
    assert cache.key_for("x") != base


def test_ttl_expires_entries(client, monkeypatch):
    post(client)
    with store._connect() as db:
        db.execute("UPDATE report_cache SET created = datetime('now', '-25 hours')")
    post(client)
    assert len(client.calls) == 2


def test_url_and_image_requests_are_not_cached(client, monkeypatch):
    monkeypatch.setattr("app.inputs.normalize_url",
                        lambda url: __import__("app.schemas", fromlist=["x"]).NormalizedInput(
                            input_type="url", text="article", source_url=url))
    post(client, {"kind": "url", "url": "https://a.test/x"})
    post(client, {"kind": "url", "url": "https://a.test/x"})
    assert len(client.calls) == 2


@pytest.mark.parametrize("event", [
    {"type": "trace", "status": "failed", "message": "A step failed"},
    {"type": "trace", "status": "completed", "message": "Source problem: guardian is unavailable."}])
def test_runs_with_a_failure_or_missing_source_are_not_eligible(event):
    assert cache.eligible([{"type": "trace", "status": "completed", "message": "ok"}])
    assert not cache.eligible([event])


def test_failed_run_is_not_cached(client, monkeypatch):
    def boom(inp):
        raise RuntimeError("x")

    monkeypatch.setattr(orchestrator, "extract_claims", boom)
    post(client)
    assert cache.get(BODY["text"]) is None
