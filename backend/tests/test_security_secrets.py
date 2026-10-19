"""API keys must not appear in SSE events, stored runs, logs or user-facing errors."""

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agents, inputs, main, orchestrator, store
from app.resilience import call_with_retry, reset_breakers
from app.retrievers import factcheck, guardian
from app.retrievers.search import make_search_fn
from app.schemas import ClaimExtraction
from test_orchestrator import make_claim

KEYS = {
    "GEMINI_API_KEY": "SENTINEL-gemini-7f3a91",
    "GUARDIAN_API_KEY": "SENTINEL-guardian-7f3a91",
    "FACTCHECK_API_KEY": "SENTINEL-factcheck-7f3a91",
    "FIRECRAWL_API_KEY": "SENTINEL-firecrawl-7f3a91",
}


def leaked(*blobs):
    text = "\n".join(str(b) for b in blobs)
    return [k for k, v in KEYS.items() if v in text]


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    reset_breakers()
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("NEWS_DB", str(tmp_path / "s.db"))
    monkeypatch.setitem(call_with_retry.__kwdefaults__, "sleep", lambda s: None)


def failing_client(status=500):
    """Echoes the full request URL, key included, in the body and the status error."""
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=f"boom {r.url}")))


def sse(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def run_api(monkeypatch, search_client, extract=None):
    monkeypatch.setattr(main, "make_search_fn",
                        lambda settings, budget: make_search_fn(settings, budget, client=search_client))
    monkeypatch.setattr(orchestrator, "extract_claims",
                        extract or (lambda inp: ClaimExtraction(claims=[make_claim()], notes="n")))
    resp = TestClient(main.app).post("/api/check", json={"kind": "text", "text": "hello"})
    events = sse(resp)
    run_id = events[-1]["run_id"]
    return resp, events, store.load_run(run_id)


@pytest.mark.parametrize("status", [500, 429, 401, 403])
def test_retriever_http_errors_leave_only_fixed_notes(status):
    notes = []
    assert guardian.search("q", notes, failing_client(status)) == []
    assert factcheck.search("q", notes, failing_client(status)) == []
    assert not leaked(notes)
    assert all("unavailable" in n for n in notes)


def test_pipeline_with_failing_sources_leaks_nothing(monkeypatch):
    def gemini_down(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(orchestrator, "check_evidence", gemini_down)
    resp, events, stored = run_api(monkeypatch, failing_client())
    assert not leaked(resp.text, json.dumps(stored))


def test_firecrawl_500_gives_fixed_message(monkeypatch):
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text=f"{r.headers['authorization']} {r.url}"))
    with pytest.raises(inputs.InputError) as e:
        inputs.normalize_url("https://example.com/a", transport=transport, resolver=lambda h: ["93.184.216.34"])
    assert not leaked(e.value.message, str(e.value))


def test_firecrawl_transport_error_gives_fixed_message(monkeypatch):
    def handler(r):
        raise httpx.ConnectError(f"cannot reach {r.url} with {r.headers['authorization']}")

    with pytest.raises(inputs.InputError) as e:
        inputs.normalize_url("https://example.com/a", transport=httpx.MockTransport(handler),
                             resolver=lambda h: ["93.184.216.34"])
    assert not leaked(e.value.message, str(e.value), e.value.__cause__)


def test_api_key_only_travels_in_header_for_firecrawl():
    seen = []
    transport = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={"success": False}))
    with pytest.raises(inputs.InputError):
        inputs.normalize_url("https://example.com/a", transport=transport, resolver=lambda h: ["93.184.216.34"])
    assert not leaked(seen[0].url, seen[0].content)


def test_stored_request_does_not_hold_keys(monkeypatch):
    _, _, stored = run_api(monkeypatch, failing_client(), extract=lambda inp: ClaimExtraction(claims=[]))
    assert not leaked(json.dumps(stored))


def test_exception_text_with_key_not_shown_in_sse_or_store(monkeypatch):
    err = httpx.HTTPStatusError("Server error for url", request=httpx.Request(
        "GET", f"https://content.guardianapis.com/search?api-key={KEYS['GUARDIAN_API_KEY']}"),
        response=httpx.Response(400))

    def boom(*a, **k):
        raise err

    monkeypatch.setattr(orchestrator, "check_evidence", boom)
    resp, events, stored = run_api(monkeypatch, failing_client())
    assert not leaked(resp.text, json.dumps(stored))


def test_exception_message_with_key_is_not_traced(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(f"GET https://x.test/search?api-key={KEYS['GUARDIAN_API_KEY']} failed")

    monkeypatch.setattr(orchestrator, "check_evidence", boom)
    resp, events, stored = run_api(monkeypatch, failing_client())
    assert not leaked(resp.text, json.dumps(stored))


def test_exception_message_with_key_is_not_logged(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError(f"GET https://x.test/search?api-key={KEYS['GUARDIAN_API_KEY']} failed")

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(orchestrator, "check_evidence", boom)
    run_api(monkeypatch, failing_client())
    assert not leaked(caplog.text)


@pytest.mark.parametrize("mod", [guardian, factcheck])
def test_httpx_request_logging_does_not_expose_query_keys(mod, caplog):
    caplog.set_level(logging.INFO)
    mod.search("q", [], failing_client(200))
    assert not leaked(caplog.text)


@pytest.mark.parametrize("mod, name", [(guardian, "GUARDIAN_API_KEY"), (factcheck, "FACTCHECK_API_KEY")])
def test_status_error_text_does_not_carry_the_key(mod, name):
    client = failing_client(500)
    caught = []
    real = mod.call_with_retry

    def spy(fn, **kw):
        try:
            return real(fn, **kw)
        except Exception as e:
            caught.append(str(e))
            raise

    mod.call_with_retry = spy
    try:
        mod.search("q", [], client)
    finally:
        mod.call_with_retry = real
    assert KEYS[name] not in caught[0]


def test_get_run_404_has_fixed_body(monkeypatch):
    r = TestClient(main.app).get("/api/runs/SENTINEL-nope")
    assert r.status_code == 404 and not leaked(r.text)


def test_gemini_client_error_path_shows_fixed_message(monkeypatch):
    class Boom:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise RuntimeError(f"bad key {KEYS['GEMINI_API_KEY']}")

    monkeypatch.setattr(agents, "_get_client", lambda: Boom)
    resp = TestClient(main.app).post("/api/check", json={"kind": "text", "text": "hello"})
    errs = [e for e in sse(resp) if e["type"] == "error"]
    assert errs and errs[0]["message"] == main.INTERNAL_MESSAGE
    assert not leaked(errs)
