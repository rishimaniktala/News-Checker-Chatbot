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
    monkeypatch.setattr(main, "make_search_fn", lambda settings, **kw: search)
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


def test_health_lists_models_and_key_booleans_only(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SENTINEL-KEY-123")
    monkeypatch.setenv("MODEL_PRIMARY", "pm")
    monkeypatch.setenv("MODEL_FALLBACK", "fm")
    body = client.get("/health").json()
    assert body["models"] == {"primary": "pm", "fallback": "fm"}
    assert body["keys_configured"]["gemini"] is True
    assert "SENTINEL" not in json.dumps(body)


def test_ready_ok_and_503_when_db_unwritable(client, monkeypatch):
    assert client.get("/ready").json() == {"status": "ready"}
    monkeypatch.setenv("NEWS_DB", "/nonexistent-dir/x.db")
    r = client.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_request_id_is_echoed_or_generated(client):
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    made = client.get("/health").headers["x-request-id"]
    assert made and made != "-"
    bad = client.get("/health", headers={"X-Request-ID": "x y\n<script>"}).headers["x-request-id"]
    assert bad != "x y\n<script>"


def test_runs_token_required_only_when_set(client, monkeypatch):
    fake_pipeline(monkeypatch)
    run_id = events_of(client.post("/api/check", json={"kind": "text", "text": "hello"}))[-1]["run_id"]
    assert client.get(f"/api/runs/{run_id}").status_code == 200
    monkeypatch.setenv("RUNS_TOKEN", "s3cret")
    assert client.get(f"/api/runs/{run_id}").status_code == 401
    assert client.get(f"/api/runs/{run_id}", headers={"X-Runs-Token": "wrong"}).status_code == 401
    assert client.get(f"/api/runs/{run_id}", headers={"X-Runs-Token": "s3cret"}).status_code == 200


def test_done_event_and_stored_run_carry_models_and_call_log(client, monkeypatch):
    from app import llm
    fake_pipeline(monkeypatch)
    real = orchestrator.extract_claims

    def extract(inp):
        llm.current_log().calls.append(llm.CallRecord("extract", "P", False, 5, 6, 7))
        llm.current_log().calls.append(llm.CallRecord("judge", "F", True, 1, 2, 3))
        return real(inp)

    monkeypatch.setattr(orchestrator, "extract_claims", extract)
    events = events_of(client.post("/api/check", json={"kind": "text", "text": "hello"}))
    done = events[-1]
    assert done["models_used"] == ["P", "F"] and done["fallback_used"] is True
    assert any("Switched to the backup model F" in e.get("message", "") for e in events)
    stored = client.get(f"/api/runs/{done['run_id']}").json()
    assert stored["calls"][1] == {"role": "judge", "model": "F", "fallback_used": True,
                                  "tokens_in": 1, "tokens_out": 2, "latency_ms": 3}


def test_log_lines_are_json_with_ids_and_never_hold_keys(client, monkeypatch):
    import io
    import logging
    from app import logging_setup
    monkeypatch.setenv("GEMINI_API_KEY", "SENTINEL-KEY-123")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging_setup.JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.INFO)

    def boom(inp):
        raise AgentError("bad key SENTINEL-KEY-123")

    monkeypatch.setattr(orchestrator, "extract_claims", boom)
    try:
        resp = client.post("/api/check", json={"kind": "text", "text": "hello"}, headers={"X-Request-ID": "rid-1"})
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
    out = buf.getvalue()
    assert "SENTINEL" not in out and "SENTINEL" not in resp.text
    lines = [json.loads(line) for line in out.splitlines()]
    failed = [entry for entry in lines if "failed" in entry["msg"]]
    assert failed and failed[0]["request_id"] == "rid-1" and failed[0]["run_id"] != "-"


def test_disconnect_before_first_event_stops_the_worker(monkeypatch, tmp_path):
    import asyncio
    import threading
    import time
    stopped = threading.Event()

    def slow_work(req, run_id, q, stop):
        stop.wait(5)
        if stop.is_set():
            stopped.set()

    monkeypatch.setattr(main, "_work", slow_work)

    async def drive():
        sent = []
        gone_at = time.monotonic() + 0.2

        async def receive():
            if time.monotonic() < gone_at:
                await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        body = b'{"kind": "text", "text": "x"}'
        scope = {"type": "http", "method": "POST", "path": "/api/check", "raw_path": b"/api/check",
                 "query_string": b"", "headers": [(b"content-type", b"application/json"),
                                                  (b"content-length", str(len(body)).encode())],
                 "client": ("1.2.3.4", 1), "server": ("t", 80), "scheme": "http", "http_version": "1.1"}
        chunks = iter([{"type": "http.request", "body": body, "more_body": False}])

        async def first_receive():
            try:
                return next(chunks)
            except StopIteration:
                return await receive()

        await main.app(scope, first_receive, send)

    asyncio.run(drive())
    assert stopped.wait(2)
    assert main._active_runs == 0
