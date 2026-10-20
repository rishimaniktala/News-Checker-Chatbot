"""API hardening: rate limit, concurrency cap, request ids, runs token, readiness, retention, disconnects, CORS."""

import asyncio
import json
import re
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import llm, main, store
from test_failure_injection import FAKE_KEYS, claim_json, extraction_json, offline, sleeps
from test_v2_fallback import V2Gemini, fixed_search

BODY = {"kind": "text", "text": "Sweden banned cash."}
REAL_CONNECT = sqlite3.connect
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def api(offline, monkeypatch):
    """Returns (client, install) where install(gemini) routes the app to a fake model."""
    monkeypatch.setenv("CACHE_TTL_HOURS", "0")
    gemini = V2Gemini()
    monkeypatch.setattr(llm, "_get_client", lambda: gemini)
    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget, **kw: fixed_search())
    client = TestClient(main.app)
    client.gemini = gemini
    return client


def events_of(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def wait_idle(seconds=3):
    deadline = time.time() + seconds
    while main._active_runs and time.time() < deadline:
        time.sleep(0.01)
    return main._active_runs == 0


# ------------------------------------------------------------------ rate limit

def test_over_the_limit_gets_429_before_any_stream(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    codes = [api.post("/api/check", json=BODY).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_429_carries_retry_after_and_json_not_an_event_stream(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    api.post("/api/check", json=BODY)
    resp = api.post("/api/check", json=BODY)
    assert int(resp.headers["retry-after"]) >= 1 and resp.headers["content-type"].startswith("application/json")
    assert "data:" not in resp.text


def test_a_rate_limited_request_never_reaches_the_model(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    api.post("/api/check", json=BODY)
    wait_idle()
    before = len(api.gemini.calls)
    api.post("/api/check", json=BODY)
    assert len(api.gemini.calls) == before


def test_a_forged_forwarded_for_header_does_not_buy_a_fresh_bucket(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    api.post("/api/check", json=BODY)
    resp = api.post("/api/check", json=BODY, headers={"X-Forwarded-For": "9.9.9.9", "X-Real-IP": "8.8.8.8"})
    assert resp.status_code == 429


def test_a_limit_of_zero_means_unlimited(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    assert {api.post("/api/check", json=BODY).status_code for _ in range(5)} == {200}


# ------------------------------------------------------------------ concurrency cap

def test_the_concurrency_cap_refuses_extra_runs_and_frees_the_slot(api, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    entered, release = threading.Event(), threading.Event()

    def slow_extract(contents):
        entered.set()
        release.wait(5)
        return extraction_json(claim_json())

    api.gemini.handlers["extract"] = slow_extract
    first: list = []
    t = threading.Thread(target=lambda: first.append(api.post("/api/check", json=BODY)))
    t.start()
    assert entered.wait(3)
    busy = api.post("/api/check", json=BODY)
    release.set()
    t.join(5)
    assert busy.status_code == 429 and int(busy.headers["retry-after"]) >= 1
    assert first[0].status_code == 200 and events_of(first[0])[-1]["type"] == "done"
    assert wait_idle() and api.post("/api/check", json=BODY).status_code == 200


def test_a_run_that_errors_still_frees_its_slot(api, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    api.gemini.handlers["extract"] = "<html>"
    api.post("/api/check", json=BODY)
    assert wait_idle()
    assert api.post("/api/check", json=BODY).status_code == 200


def test_a_bad_input_run_still_frees_its_slot(api):
    api.post("/api/check", json={"kind": "text", "text": ""})
    assert wait_idle()


# ------------------------------------------------------------------ request id

def test_a_good_request_id_is_echoed(api):
    assert api.get("/health", headers={"X-Request-ID": "abc-123.x_y"}).headers["x-request-id"] == "abc-123.x_y"


def test_a_missing_request_id_is_generated(api):
    assert re.fullmatch(r"[0-9a-f]{16}", api.get("/health").headers["x-request-id"])


def test_two_requests_get_two_different_generated_ids(api):
    assert api.get("/health").headers["x-request-id"] != api.get("/health").headers["x-request-id"]


@pytest.mark.parametrize("bad", ["has space", "a" * 65, "semi;colon", "<script>", "x=y"])
def test_an_unsafe_request_id_is_replaced(api, bad):
    resp = api.get("/health", headers={"X-Request-ID": bad})
    assert resp.headers["x-request-id"] != bad and re.fullmatch(r"[0-9a-f]{16}", resp.headers["x-request-id"])


def test_the_request_id_is_on_429_and_stream_responses(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    ok = api.post("/api/check", json=BODY, headers={"X-Request-ID": "r1"})
    limited = api.post("/api/check", json=BODY, headers={"X-Request-ID": "r2"})
    assert (ok.headers["x-request-id"], limited.headers["x-request-id"]) == ("r1", "r2")


# ------------------------------------------------------------------ /api/runs token

def stored_run_id(api):
    return events_of(api.post("/api/check", json=BODY))[-1]["run_id"]


def test_runs_are_open_when_no_token_is_set(api):
    assert api.get(f"/api/runs/{stored_run_id(api)}").status_code == 200


def test_runs_need_the_token_when_one_is_set(api, monkeypatch):
    run_id = stored_run_id(api)
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get(f"/api/runs/{run_id}").status_code == 401


def test_runs_reject_a_wrong_token(api, monkeypatch):
    run_id = stored_run_id(api)
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get(f"/api/runs/{run_id}", headers={"X-Runs-Token": "s3cret-tokeN"}).status_code == 401


def test_runs_reject_a_token_that_is_a_prefix(api, monkeypatch):
    run_id = stored_run_id(api)
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get(f"/api/runs/{run_id}", headers={"X-Runs-Token": "s3cret"}).status_code == 401


def test_runs_accept_the_right_token(api, monkeypatch):
    run_id = stored_run_id(api)
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get(f"/api/runs/{run_id}", headers={"X-Runs-Token": "s3cret-token"}).status_code == 200


def test_an_unknown_run_is_404_only_after_the_token_passes(api, monkeypatch):
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get("/api/runs/nope").status_code == 401
    assert api.get("/api/runs/nope", headers={"X-Runs-Token": "s3cret-token"}).status_code == 404


def test_a_401_does_not_reveal_whether_the_run_exists(api, monkeypatch):
    run_id = stored_run_id(api)
    monkeypatch.setenv("RUNS_TOKEN", "s3cret-token")
    assert api.get(f"/api/runs/{run_id}").text == api.get("/api/runs/nope").text


def test_the_stored_run_carries_the_model_call_log_and_no_key(api):
    run = api.get(f"/api/runs/{stored_run_id(api)}").json()
    assert run["calls"] and {"role", "model", "fallback_used"} <= set(run["calls"][0])
    assert not any(k in json.dumps(run) for k in FAKE_KEYS)


# ------------------------------------------------------------------ readiness

def test_ready_when_the_database_is_writable(api):
    resp = api.get("/ready")
    assert resp.status_code == 200 and resp.json() == {"status": "ready"}


def test_not_ready_when_the_database_cannot_be_opened(api, monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "missing-dir" / "x.db"))
    resp = api.get("/ready")
    assert resp.status_code == 503 and "missing-dir" not in resp.text


def test_not_ready_when_the_database_is_locked(api, monkeypatch, tmp_path):
    path = tmp_path / "locked.db"
    monkeypatch.setenv("NEWS_DB", str(path))
    store.check_writable()
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    monkeypatch.setattr(sqlite3, "connect", lambda p, *a, **k: REAL_CONNECT(p, timeout=0.05))
    try:
        assert api.get("/ready").status_code == 503
    finally:
        holder.close()


def test_health_does_not_touch_the_database(api, monkeypatch, tmp_path):
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "missing-dir" / "x.db"))
    assert api.get("/health").status_code == 200


# ------------------------------------------------------------------ retention

def insert_run(run_id, age_days):
    store.save_run(run_id, {}, [], None, 0, 0)
    with store._connect() as db:
        db.execute("UPDATE runs SET created = datetime('now', ?) WHERE run_id = ?", (f"-{age_days} days", run_id))


def test_purge_removes_old_runs_only(offline):
    insert_run("old", 40)
    insert_run("new", 2)
    assert store.purge_older_than(30) == 1
    assert store.load_run("old") is None and store.load_run("new") is not None


def test_purge_keeps_a_run_just_inside_the_window(offline):
    insert_run("edge", 29)
    assert store.purge_older_than(30) == 0


def test_purge_also_drops_old_cache_rows_and_keeps_fresh_ones(offline):
    store.cache_put("old", {"a": 1})
    store.cache_put("fresh", {"a": 2})
    with store._connect() as db:
        db.execute("UPDATE report_cache SET created = datetime('now', '-40 days') WHERE key = 'old'")
    store.purge_older_than(30)
    assert store.cache_get("old", 24 * 365) is None and store.cache_get("fresh", 24) == {"a": 2}


def test_startup_purges_with_the_configured_retention(api, monkeypatch):
    insert_run("old", 3)
    insert_run("new", 0.5)
    monkeypatch.setenv("RUNS_RETENTION_DAYS", "1")
    with TestClient(main.app):
        pass
    assert store.load_run("old") is None and store.load_run("new") is not None


def test_a_broken_purge_does_not_stop_startup(api, monkeypatch):
    monkeypatch.setattr(store, "purge_older_than", lambda days: (_ for _ in ()).throw(RuntimeError("disk")))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


# ------------------------------------------------------------------ disconnect

def drive_then_disconnect(gone_after=0.3):
    async def drive():
        body = json.dumps(BODY).encode()
        scope = {"type": "http", "method": "POST", "path": "/api/check", "raw_path": b"/api/check", "query_string": b"",
                 "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                 "client": ("1.2.3.4", 1), "server": ("t", 80), "scheme": "http", "http_version": "1.1"}
        sent_body = False
        gone_at = time.monotonic() + gone_after

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            while time.monotonic() < gone_at:
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        await main.app(scope, receive, send)

    asyncio.run(drive())


def test_a_client_that_leaves_mid_run_stops_the_worker_before_the_next_model_call(api):
    entered, release = threading.Event(), threading.Event()

    def slow_extract(contents):
        entered.set()
        release.wait(5)
        return extraction_json(claim_json())

    api.gemini.handlers["extract"] = slow_extract
    drive_then_disconnect()
    assert entered.is_set()
    release.set()
    assert wait_idle()
    assert api.gemini.n("verify") == 0 and api.gemini.n("judge") == 0


def test_a_run_abandoned_by_the_client_is_not_saved_as_finished(api, monkeypatch):
    saved = []
    monkeypatch.setattr(main, "_save", lambda run_id, *a: saved.append(run_id))
    release = threading.Event()
    api.gemini.handlers["extract"] = lambda contents: (release.wait(5), extraction_json(claim_json()))[1]
    drive_then_disconnect()
    release.set()
    assert wait_idle() and saved == []


# ------------------------------------------------------------------ CORS and body size

def test_cors_exposes_retry_after_on_a_429(api, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    api.post("/api/check", json=BODY, headers=ORIGIN)
    resp = api.post("/api/check", json=BODY, headers=ORIGIN)
    exposed = resp.headers["access-control-expose-headers"].lower()
    assert resp.status_code == 429 and "retry-after" in exposed and "x-request-id" in exposed


def test_cors_allows_the_frontend_origin_only(api):
    assert api.get("/health", headers=ORIGIN).headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in api.get("/health", headers={"Origin": "https://evil.example"}).headers


def test_cors_preflight_allows_the_runs_token_header(api):
    resp = api.options("/api/runs/x", headers={**ORIGIN, "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "X-Runs-Token"})
    assert resp.status_code == 200 and "x-runs-token" in resp.headers["access-control-allow-headers"].lower()


def test_an_oversized_body_is_refused_with_413(api):
    resp = api.post("/api/check", content=b"x" * 8_100_000, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
