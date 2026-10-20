"""Auth, rate limit, concurrency cap, body limits and the report cache under hostile input."""

import asyncio
import inspect
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import cache, main, store

BODY = {"kind": "text", "text": "hello"}
DONE = {"type": "done", "run_id": "r", "cost_usd": 0, "latency_ms": 0, "tokens_in": 0, "tokens_out": 0,
        "cached": False, "models_used": [], "fallback_used": False}


@pytest.fixture
def quick_work(monkeypatch):
    """Runs end at once, with no model or network."""
    monkeypatch.setattr(main, "_work", lambda req, run_id, q, stop: q.put(dict(DONE, run_id=run_id)))


@pytest.fixture
def client():
    return TestClient(main.app)


def test_runs_token_is_compared_in_constant_time():
    src = inspect.getsource(main.get_run)
    assert "hmac.compare_digest" in src and "== token" not in src and "token ==" not in src


@pytest.fixture
def stored_run(client, quick_work):
    return store.save_run("abc123", {}, [], None, 0, 0) or "abc123"


@pytest.mark.parametrize("header", [None, "", "wrong", "s3cre", "s3cret ", "S3CRET", "é", "s3cret\x00"])
def test_wrong_token_gets_the_same_fixed_401(client, monkeypatch, stored_run, header):
    monkeypatch.setenv("RUNS_TOKEN", "s3cret")
    headers = {} if header is None else {"X-Runs-Token": header.encode("latin-1")}
    r = client.get(f"/api/runs/{stored_run}", headers=headers)
    assert r.status_code == 401 and r.json() == {"detail": "Unauthorized."}


def test_unknown_run_with_a_wrong_token_is_401_not_404(client, monkeypatch):
    monkeypatch.setenv("RUNS_TOKEN", "s3cret")
    assert client.get("/api/runs/nope", headers={"X-Runs-Token": "x"}).status_code == 401


def test_correct_token_reads_the_run(client, monkeypatch, stored_run):
    monkeypatch.setenv("RUNS_TOKEN", "s3cret")
    assert client.get(f"/api/runs/{stored_run}", headers={"X-Runs-Token": "s3cret"}).status_code == 200


@pytest.mark.parametrize("run_id", ["' OR 1=1 --", "x%27%3B%20DROP%20TABLE%20runs%3B--", "..%2f..%2fetc%2fpasswd", "a" * 5000])
def test_run_id_is_data_not_sql_or_path(client, stored_run, run_id):
    assert client.get(f"/api/runs/{run_id}").status_code in (404, 414)
    assert store.load_run(stored_run) is not None


SPOOFS = [
    {"X-Forwarded-For": "9.9.9.{n}"}, {"X-Real-IP": "9.9.9.{n}"}, {"Forwarded": "for=9.9.9.{n}"},
    {"X-Forwarded-For": "9.9.9.{n}, 10.0.0.1"}, {"CF-Connecting-IP": "9.9.9.{n}"}, {"True-Client-IP": "9.9.9.{n}"},
]


@pytest.mark.parametrize("spoof", SPOOFS, ids=lambda s: next(iter(s)))
def test_rate_limit_cannot_be_bypassed_with_forwarding_headers(client, monkeypatch, quick_work, spoof):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    codes = [client.post("/api/check", json=BODY, headers={k: v.format(n=i) for k, v in spoof.items()}).status_code
             for i in range(5)]
    assert codes[:2] == [200, 200] and set(codes[2:]) == {429}


def test_429_bodies_are_fixed_and_carry_retry_after(client, monkeypatch, quick_work):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    client.post("/api/check", json=BODY)
    r = client.post("/api/check", json=BODY)
    assert r.json() == {"detail": "Too many checks from your address. Please wait a moment."}
    assert int(r.headers["retry-after"]) >= 1


def test_rate_limit_table_stays_bounded(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    for i in range(10_050):
        main._buckets[f"ip{i}"] = [0.0, time.monotonic() - 120]
    main._retry_after_for_rate("fresh")
    assert len(main._buckets) < 100


def test_cap_refuses_extra_runs_with_a_fixed_body_then_recovers(client, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    hold, started = threading.Event(), threading.Event()

    def slow(req, run_id, q, stop):
        started.set()
        hold.wait(5)
        q.put(dict(DONE, run_id=run_id))

    monkeypatch.setattr(main, "_work", slow)
    first = threading.Thread(target=lambda: client.post("/api/check", json=BODY))
    first.start()
    assert started.wait(3)
    busy = client.post("/api/check", json=BODY)
    assert busy.status_code == 429 and busy.json() == {"detail": "The checker is busy. Please try again shortly."}
    hold.set()
    first.join(5)
    monkeypatch.setattr(main, "_work", lambda req, run_id, q, stop: q.put(dict(DONE, run_id=run_id)))
    assert client.post("/api/check", json=BODY).status_code == 200
    assert main._active_runs == 0


@pytest.mark.parametrize("exc", [RuntimeError("x"), KeyboardInterrupt(), main.Cancelled()])
def test_slot_is_released_when_the_worker_raises(monkeypatch, exc):
    import queue

    def boom(req, run_id, q, stop):
        raise exc

    monkeypatch.setattr(main, "_work", boom)
    assert main._take_run_slot() and main._active_runs == 1
    with pytest.raises(type(exc)):
        main._worker(BODY, "r1", queue.Queue(), threading.Event(), "rid")
    assert main._active_runs == 0


def _wait(cond, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_slot_is_released_when_the_client_disconnects_mid_stream(monkeypatch):
    stopped = threading.Event()

    def slow(req, run_id, q, stop):
        stop.wait(5)
        stopped.set()

    monkeypatch.setattr(main, "_work", slow)

    async def drive():
        body = json.dumps(BODY).encode()
        scope = {"type": "http", "method": "POST", "path": "/api/check", "raw_path": b"/api/check",
                 "query_string": b"", "headers": [(b"content-type", b"application/json"),
                                                  (b"content-length", str(len(body)).encode())],
                 "client": ("1.2.3.4", 1), "server": ("t", 80), "scheme": "http", "http_version": "1.1"}
        sent_body = False

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(0.2)
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        await main.app(scope, receive, send)

    asyncio.run(drive())
    assert stopped.wait(3)
    assert _wait(lambda: main._active_runs == 0)


def test_thread_start_failure_releases_the_slot(client, monkeypatch):
    def no_thread(*a, **k):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(main.threading, "Thread", no_thread)
    with pytest.raises(RuntimeError):
        client.post("/api/check", json=BODY)
    assert main._active_runs == 0


def test_oversized_content_length_is_refused_before_parsing(client):
    r = client.post("/api/check", content=b"{}", headers={"Content-Length": str(main.MAX_BODY_BYTES + 1),
                                                           "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"detail": "Request too large."}


@pytest.mark.parametrize("length", ["-5"])
def test_garbage_content_length_never_crashes_the_server(client, length):
    try:
        r = client.post("/api/check", content=b"{}", headers={"Content-Length": length,
                                                               "Content-Type": "application/json"})
    except Exception as e:
        pytest.fail(f"{type(e).__name__} escaped the middleware")
    assert r.status_code < 500


def test_chunked_body_over_the_cap_is_refused(client, quick_work):
    chunk = b"x" * 1_000_000

    def body():
        yield b'{"kind": "text", "text": "'
        for _ in range(main.MAX_BODY_BYTES // len(chunk) + 2):
            yield chunk
        yield b'"}'

    r = client.post("/api/check", content=body(), headers={"Content-Type": "application/json"})
    assert r.status_code in (411, 413)


@pytest.mark.parametrize("payload", [b"[]", b'"str"', b"null", b"{", b"\xff\xfe", b"1" * 5000])
def test_non_object_or_broken_json_is_a_clean_4xx(client, quick_work, payload):
    r = client.post("/api/check", content=payload, headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422) and main._active_runs == 0


@pytest.mark.parametrize("req", [
    {"kind": "text", "text": 5}, {"kind": ["text"]}, {"kind": "text", "text": {"a": 1}}, {"kind": "image", "image_b64": 3},
    {"kind": "url", "url": ["x"]}, {},
])
def test_wrongly_typed_fields_end_in_a_bad_input_error_event(client, req):
    events = [json.loads(x[6:]) for x in client.post("/api/check", json=req).text.split("\n\n") if x.startswith("data: ")]
    assert events[-1]["type"] == "done" and any(e["type"] == "error" for e in events)
    assert not any(e.get("code") == "internal" for e in events)


KEY_BASE = "Sweden has banned cash payments in shops"


def key(text):
    return cache.key_for(text)


@pytest.mark.parametrize("a,b", [
    ("Sweden banned cash", "Sweden banned cаsh"),
    ("Sweden banned cash", "Sweden banned cash."),
    ("The rate is 1,000", "The rate is 10,00"),
    ("O2 levels rose", "02 levels rose"),
    ("Sweden joined NATO", "Sweden did not join NATO"),
    ("a​b", "ab"),
    ("Paris is in France", "Ｐaris is in France"),
    ("x\x00y", "xy"),
    ("a b", "a ​b"),
])
def test_visually_or_semantically_different_texts_do_not_share_a_cache_key(a, b):
    assert key(a) != key(b)


@pytest.mark.parametrize("a,b", [("Turkey recognised it", "turkey recognised it"), ("US sanctions", "us sanctions")])
def test_case_only_differences_that_change_meaning_do_not_collide(a, b):
    assert key(a) != key(b)


def test_whitespace_normalisation_still_merges_identical_claims():
    assert key("  Sweden   banned\tcash ") == key("Sweden banned cash")


def test_key_changes_with_models_prompts_and_sources(monkeypatch):
    base = key("claim")
    monkeypatch.setenv("MODEL_PRIMARY", "other-model")
    assert key("claim") != base
    monkeypatch.delenv("MODEL_PRIMARY")
    monkeypatch.setenv("SOURCES", "guardian")
    assert key("claim") != base


def test_key_separator_cannot_be_forged_through_the_text(monkeypatch):
    monkeypatch.setenv("MODEL_PRIMARY", "m")
    forged = "claim\x1fm\x1fv2\x1ffactcheck,guardian,web"
    assert key(forged) != key("claim")


def run_text(client, text, monkeypatch):
    return [json.loads(x[6:]) for x in client.post("/api/check", json={"kind": "text", "text": text}).text.split("\n\n")
            if x.startswith("data: ")]


def test_cached_report_for_one_text_is_never_served_for_another(client, monkeypatch):
    cache.put("Sweden banned cash", {"run_id": "old", "overall_label": "FALSE", "marker": "POISON"})
    monkeypatch.setattr(main, "run_check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ran")))
    for other in ("Sweden banned cash!", "Norway banned cash", "Sweden banned cashless"):
        events = run_text(client, other, monkeypatch)
        assert "POISON" not in json.dumps(events) and events[-1]["cached"] is False
    hit = run_text(client, "  Sweden banned   cash ", monkeypatch)
    assert hit[-1]["cached"] is True and next(e for e in hit if e["type"] == "verdict")["report"]["run_id"] != "old"


def test_url_and_image_requests_never_read_or_write_the_cache(client, monkeypatch):
    cache.put("https://example.com/a", {"marker": "POISON"})
    for req in ({"kind": "url", "url": "https://example.com/a"}, {"kind": "image", "image_b64": "AAAA", "mime": "image/png"}):
        text, hit = main._cached_report(req)
        assert (text, hit) == (None, None)


def test_failed_or_degraded_runs_are_not_cacheable():
    assert not cache.eligible([{"type": "trace", "status": "failed"}])
    assert not cache.eligible([{"type": "trace", "status": "completed", "message": "Source problem: web search"}])
    assert cache.eligible([{"type": "trace", "status": "completed", "message": "ok"}])


def test_cache_ttl_is_a_bound_parameter_not_sql(monkeypatch):
    cache.put("t", {"a": 1})
    assert store.cache_get(cache.key_for("t"), 1) == {"a": 1}
    assert store.cache_get(cache.key_for("t"), "1 hours'); DROP TABLE report_cache;--") is None
    assert store.cache_get(cache.key_for("t"), 1) == {"a": 1}


def test_corrupt_cache_row_does_not_break_a_run(client, monkeypatch):
    with store._connect() as db:
        db.execute("INSERT OR REPLACE INTO report_cache (key, report) VALUES (?, ?)", (cache.key_for("zzz"), "{not json"))
    events = run_text(client, "zzz", monkeypatch)
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("length", ["abc", "1e9", " ", "0x10"])
def test_non_numeric_content_length_is_not_a_server_error(client, length):
    r = client.post("/api/check", content=b"{}", headers={"Content-Length": length, "Content-Type": "application/json"})
    assert r.status_code < 500
