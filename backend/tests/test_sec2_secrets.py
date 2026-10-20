"""Sentinel keys must stay out of every surface, including the model-router failure paths."""

import io
import json
import logging
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app import llm, logging_setup, main, orchestrator, store
from app.agents import EvidenceCheck, EvidenceDecision
from app.prompts import EXTRACTION_SYSTEM_PROMPT
from app.resilience import call_with_retry, reset_breakers
from app.retrievers import web
from app.retrievers.search import make_search_fn
from app.schemas import ClaimExtraction, EvidenceItem, RankedEvidence
from test_failure_injection import claim_json, extraction_json, verdict_json, verify_json
from test_orchestrator import make_claim

KEYS = {
    "GEMINI_API_KEY": "SENTINEL-gemini-9c41d2",
    "GUARDIAN_API_KEY": "SENTINEL-guardian-9c41d2",
    "FACTCHECK_API_KEY": "SENTINEL-factcheck-9c41d2",
    "FIRECRAWL_API_KEY": "SENTINEL-firecrawl-9c41d2",
}
GEMINI = KEYS["GEMINI_API_KEY"]


def leaked(*blobs):
    text = "\n".join(str(b) for b in blobs)
    return [k for k, v in KEYS.items() if v in text]


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    reset_breakers()
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setitem(call_with_retry.__kwdefaults__, "sleep", lambda s: None)
    monkeypatch.setenv("MODEL_PRIMARY", "pm")
    monkeypatch.setenv("MODEL_FALLBACK", "fm")
    monkeypatch.setattr(llm, "_client", None)


@pytest.fixture
def json_log():
    """Real JSON formatter on the root logger, as in production."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging_setup.JsonFormatter())
    root = logging.getLogger()
    old_handlers, old_level = root.handlers, root.level
    root.handlers, root.level = [handler], logging.DEBUG
    yield buf
    root.handlers, root.level = old_handlers, old_level


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"{code} UNAVAILABLE. url=https://g.test/v1?key={GEMINI} header x-goog-api-key: {GEMINI}")
        self.code = code


class FakeClient:
    """genai.Client stand-in. fail(system) decides which calls raise a key-bearing error."""

    def __init__(self, fail):
        self.fail, self.models, self.models_seen = fail, self, []

    def generate_content(self, model, contents, config):
        from types import SimpleNamespace
        from app import prompts
        self.models_seen.append(model)
        role = {prompts.EXTRACTION_SYSTEM_PROMPT: "extract", prompts.VERDICT_SYSTEM_PROMPT: "judge",
                prompts.VERIFY_SYSTEM_PROMPT: "verify"}.get(config.system_instruction, "other")
        if self.fail(role, model):
            raise ApiError(503)
        text = {"extract": extraction_json(claim_json()), "verify": verify_json(), "judge": verdict_json(
            quote="Real passage")}[role]
        return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5))


def evidence_search(claim, queries, round_no):
    item = EvidenceItem(id="E1", url="https://x.test/a", title="t", passage="Real passage.", rerank_score=0.8)
    return RankedEvidence(claim_id=claim.id, attempt=round_no, guardian=[item])


def sse(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def post(monkeypatch, fake, headers=None, search=evidence_search):
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
    monkeypatch.setattr(main, "make_search_fn", lambda settings, budget, **kw: search)
    client = TestClient(main.app)
    resp = client.post("/api/check", json={"kind": "text", "text": "Sweden banned cash."}, headers=headers or {})
    return client, resp, sse(resp)


def surfaces(client, resp, events, log):
    run_id = events[-1]["run_id"]
    db = sqlite3.connect(store.os.environ["NEWS_DB"])
    raw_tables = [db.execute("SELECT * FROM report_cache").fetchall(), db.execute("SELECT * FROM runs").fetchall()]
    return [resp.text, dict(resp.headers), events, store.load_run(run_id), raw_tables, log.getvalue(),
            client.get("/health").text, client.get("/ready").text, client.get(f"/api/runs/{run_id}").text]


@pytest.mark.parametrize("fail_roles", [{"extract"}, {"judge"}, {"extract", "verify", "judge"}])
def test_key_bearing_model_errors_never_reach_any_surface(monkeypatch, json_log, fail_roles):
    fake = FakeClient(lambda role, model: role in fail_roles)
    client, resp, events = post(monkeypatch, fake, headers={"X-Request-ID": "rid-1"})
    assert events[-1]["type"] == "done"
    assert leaked(*surfaces(client, resp, events, json_log)) == []


def test_fallback_path_failure_is_fixed_text_and_not_cached(monkeypatch, json_log):
    fake = FakeClient(lambda role, model: role == "judge")
    client, resp, events = post(monkeypatch, fake)
    assert set(fake.models_seen) >= {"pm", "fm"}
    assert leaked(*surfaces(client, resp, events, json_log)) == []
    assert store._connect().execute("SELECT count(*) FROM report_cache").fetchone()[0] == 0


def test_unexpected_exception_in_the_run_returns_the_fixed_message(monkeypatch, json_log):
    def boom(inp):
        raise RuntimeError(f"exploded with {GEMINI} and key={GEMINI}")
    monkeypatch.setattr(orchestrator, "extract_claims", boom)
    client, resp, events = post(monkeypatch, FakeClient(lambda r, m: False))
    err = next(e for e in events if e["type"] == "error")
    assert err["message"] == main.INTERNAL_MESSAGE
    assert leaked(*surfaces(client, resp, events, json_log)) == []


def test_router_logs_the_exception_type_not_its_text(monkeypatch, json_log):
    fake = FakeClient(lambda role, model: model == "pm")
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
    out = llm.generate(EXTRACTION_SYSTEM_PROMPT, "user", ClaimExtraction, role="extract")
    assert out.claims
    assert leaked(json_log.getvalue()) == []


def test_router_exception_text_is_raw_so_callers_must_redact(monkeypatch):
    """Documented gap, not a leak: generate() re-raises the SDK error untouched. Every caller redacts."""
    fake = FakeClient(lambda role, model: True)
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
    with pytest.raises(ApiError) as info:
        llm.generate(EXTRACTION_SYSTEM_PROMPT, "user", ClaimExtraction, role="extract")
    from app.config import redact
    assert GEMINI in str(info.value) and GEMINI not in redact(str(info.value))


def test_failed_claim_trace_message_is_redacted(monkeypatch, json_log):
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[make_claim()], notes="n"))

    def boom(c, e, tried):
        raise RuntimeError(f"search blew up at https://x.test?key={GEMINI}&api-key={GEMINI}")
    monkeypatch.setattr(orchestrator, "check_evidence", boom)
    client, resp, events = post(monkeypatch, FakeClient(lambda r, m: False))
    assert any("left unverified" in e.get("message", "") for e in events if e["type"] == "trace")
    assert leaked(*surfaces(client, resp, events, json_log)) == []


def test_web_source_errors_do_not_echo_the_request(monkeypatch, json_log):
    def handler(request):
        return httpx.Response(500, text=f"boom {request.url} {request.headers.get('authorization')}")
    client_web = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("SOURCES", "web")
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[make_claim()], notes="n"))
    monkeypatch.setattr(orchestrator, "check_evidence", lambda c, e, tried: EvidenceCheck(
        claim_id=c.id, decision=EvidenceDecision.INSUFFICIENT, reason="r"))
    search = lambda settings, budget, **kw: make_search_fn(settings, budget, client=client_web)  # noqa: E731
    monkeypatch.setattr(llm, "_get_client", lambda: FakeClient(lambda r, m: False))
    monkeypatch.setattr(main, "make_search_fn", search)
    client = TestClient(main.app)
    resp = client.post("/api/check", json={"kind": "text", "text": "hi"})
    events = sse(resp)
    notes = [e["message"] for e in events if e["type"] == "trace" and "Source problem" in e.get("message", "")]
    assert any("web search" in n for n in notes)
    assert leaked(*surfaces(client, resp, events, json_log)) == []


def test_web_search_note_and_exception_text_are_clean():
    notes = []
    transport = httpx.MockTransport(lambda r: httpx.Response(401, text=f"bad {r.url} {r.headers['authorization']}"))
    assert web.search("q", notes, httpx.Client(transport=transport)) == []
    assert leaked(notes) == [] and notes == ["web search: source unavailable"]


def test_stored_call_log_has_only_the_known_fields(monkeypatch):
    client, resp, events = post(monkeypatch, FakeClient(lambda r, m: False))
    run = store.load_run(events[-1]["run_id"])
    assert run["calls"] and all(set(c) == {"role", "model", "fallback_used", "tokens_in", "tokens_out", "latency_ms"}
                                for c in run["calls"])


def test_done_event_has_only_known_keys(monkeypatch):
    _, _, events = post(monkeypatch, FakeClient(lambda r, m: False))
    assert set(events[-1]) == {"type", "run_id", "cost_usd", "latency_ms", "tokens_in", "tokens_out", "cached",
                               "models_used", "fallback_used"}


def test_health_reports_booleans_only(monkeypatch):
    body = TestClient(main.app).get("/health").json()
    assert set(body["keys_configured"]) == {"gemini", "guardian", "factcheck", "firecrawl"}
    assert all(v is True for v in body["keys_configured"].values())
    assert leaked(body) == []


def test_ready_failure_body_is_fixed(monkeypatch):
    monkeypatch.setenv("NEWS_DB", f"/nonexistent/{GEMINI}/x.db")
    r = TestClient(main.app).get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_ready_failure_log_does_not_leak(monkeypatch, json_log):
    monkeypatch.setenv("NEWS_DB", f"/nonexistent/{GEMINI}/x.db")
    TestClient(main.app).get("/ready")
    assert leaked(json_log.getvalue()) == []


def test_json_log_redacts_a_key_in_the_message_and_the_traceback(json_log):
    log = logging.getLogger("t")
    try:
        raise RuntimeError(f"x {GEMINI}")
    except RuntimeError:
        log.exception("failed with %s", GEMINI)
    assert leaked(json_log.getvalue()) == [] and "[redacted]" in json_log.getvalue()


@pytest.mark.parametrize("rid", ["a\r\nSet-Cookie: x=1", "a\nb", "x" * 65, "<script>", "a b", ""])
def test_request_id_header_injection_is_replaced(rid):
    r = TestClient(main.app).get("/health", headers={"X-Request-ID": rid})
    echoed = r.headers["x-request-id"]
    assert echoed != rid and "\r" not in echoed and "\n" not in echoed and 1 <= len(echoed) <= 64
    assert "set-cookie" not in r.headers


def test_request_id_with_non_ascii_bytes_cannot_split_the_response():
    async def app_call():
        sent = []
        scope = {"type": "http", "method": "GET", "path": "/health", "raw_path": b"/health", "query_string": b"",
                 "headers": [(b"x-request-id", "é\r\nX-Evil: 1".encode("latin-1"))], "client": ("1.2.3.4", 1),
                 "server": ("t", 80), "scheme": "http", "http_version": "1.1"}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)
        await main.app(scope, receive, send)
        return sent

    import asyncio
    start = next(m for m in asyncio.run(app_call()) if m["type"] == "http.response.start")
    values = [v for k, v in start["headers"]]
    assert not any(b"\r" in v or b"\n" in v for v in values)
    assert not any(k == b"x-evil" for k, v in start["headers"])
