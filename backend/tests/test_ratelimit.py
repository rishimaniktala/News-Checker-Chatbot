import time

import pytest
from fastapi.testclient import TestClient

from app import main, orchestrator
from app.schemas import ClaimExtraction
from test_orchestrator import search

BODY = {"kind": "text", "text": "hello"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget, **kw: search)
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[], notes="n"))
    return TestClient(main.app)


def test_over_limit_gets_429_with_retry_after_before_streaming(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    assert [client.post("/api/check", json=BODY).status_code for _ in range(2)] == [200, 200]
    r = client.post("/api/check", json=BODY)
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/json")
    assert int(r.headers["retry-after"]) >= 1


def test_limit_is_per_client_ip(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    assert main._retry_after_for_rate("1.1.1.1") == 0
    assert main._retry_after_for_rate("1.1.1.1") > 0
    assert main._retry_after_for_rate("2.2.2.2") == 0


def test_bucket_refills_over_time(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "60")
    assert main._retry_after_for_rate("ip") == 0
    main._buckets["ip"][0] = 0.0
    main._buckets["ip"][1] = time.monotonic() - 2
    assert main._retry_after_for_rate("ip") == 0


def test_concurrency_cap_gets_429_and_slot_is_freed(client, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    assert main._take_run_slot()
    r = client.post("/api/check", json=BODY)
    assert r.status_code == 429 and r.headers["retry-after"]
    main._release_run_slot()
    assert client.post("/api/check", json=BODY).status_code == 200
    deadline = time.time() + 2
    while main._active_runs and time.time() < deadline:
        time.sleep(0.01)
    assert main._active_runs == 0
