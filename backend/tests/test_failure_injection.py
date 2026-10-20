"""Failure injection: sources and Gemini fail in controlled ways; the run must end cleanly.

Also holds the shared offline fakes (FakeGemini, mock sources, stream invariants) that
test_weird_inputs, test_integration_fixtures and test_loop_properties import.
"""

import app.llm as llm
import json
import re
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agents, main, resilience
from app.main import INTERNAL_MESSAGE
from app.prompts import EXTRACTION_SYSTEM_PROMPT, OCR_SYSTEM_PROMPT, VERDICT_SYSTEM_PROMPT
from app.retrievers.search import make_search_fn

FAKE_KEYS = ("fake-guardian-key-0001", "fake-factcheck-key-0002", "fake-gemini-key-0003", "fake-firecrawl-key-0004")
KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|Bearer\s+\S{8,}|api[-_]?key=\S+", re.I)
PASSAGE = "Sweden has not banned cash. Shops may refuse cash."
QUOTE = "Sweden has not banned cash"
SYSTEM_KIND = {EXTRACTION_SYSTEM_PROMPT: "extract", VERDICT_SYSTEM_PROMPT: "verdict", OCR_SYSTEM_PROMPT: "ocr"}


def claim_json(cid="c1", text="Sweden banned cash.", queries=("sweden cash ban",), checkworthy=True):
    return {"id": cid, "text": text, "checkworthy": checkworthy,
            "search_queries": list(queries) if checkworthy else [],
            "skip_reason": None if checkworthy else "opinion or not checkable"}


def extraction_json(*claims, notes="n"):
    return json.dumps({"claims": list(claims), "notes": notes})


def verify_json(decision="sufficient", new_queries=(), cid="c1"):
    return json.dumps({"claim_id": cid, "decision": decision, "relevant_ids": ["E1"], "reason": "r",
                       "new_search_queries": list(new_queries)})


def verdict_json(quote=QUOTE, label="FALSE", cid="c1"):
    return json.dumps({"claim_id": cid, "label": label, "confidence": 0.9, "answer": "No.", "reasoning": "Because.",
                       "citations": [{"evidence_id": "E1", "quote": quote, "stance": "refutes"}]})


class FakeGemini:
    """Stands in for genai.Client. Handlers map extract/verify/verdict/ocr to a str or a callable(contents) -> str."""

    def __init__(self, tokens=(1000, 200), **handlers):
        self.handlers, self.tokens = handlers, tokens
        self.calls: Counter = Counter()
        self.prompts: list[tuple[str, object]] = []
        self.tools_seen: list[object] = []
        self.models = self

    def generate_content(self, model, contents, config):
        kind = SYSTEM_KIND.get(config.system_instruction, "verify")
        self.calls[kind] += 1
        self.prompts.append((kind, contents))
        self.tools_seen.append(config.tools)
        handler = self.handlers[kind]
        text = handler(contents) if callable(handler) else handler
        return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
            prompt_token_count=self.tokens[0], candidates_token_count=self.tokens[1]))


def default_gemini(**overrides):
    handlers = {"extract": extraction_json(claim_json()), "verify": verify_json(), "verdict": verdict_json(),
                "ocr": json.dumps({"text": "", "context_note": "blank", "is_legible": False})}
    handlers.update(overrides)
    return FakeGemini(**handlers)


def guardian_body(passage=PASSAGE):
    return {"response": {"results": [{
        "webUrl": "https://www.theguardian.com/world/sweden-cash", "webTitle": "Sweden and cash",
        "webPublicationDate": "2024-03-12T14:05:00Z", "fields": {"headline": "Sweden and cash", "bodyText": passage}}]}}


class Sources:
    """Mock Guardian and Fact Check over httpx.MockTransport. A status other than 200 fails every request."""

    def __init__(self, guardian=200, factcheck=200):
        self.status = {"guardian": guardian, "factcheck": factcheck}
        self.hits: Counter = Counter()
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, req: httpx.Request) -> httpx.Response:
        name = "guardian" if "guardian" in req.url.host else "factcheck"
        self.hits[name] += 1
        if self.status[name] != 200:
            return httpx.Response(self.status[name])
        return httpx.Response(200, json=guardian_body() if name == "guardian" else {"claims": []})


@pytest.fixture
def sleeps(monkeypatch):
    """call_with_retry binds time.sleep as a default at import, so patch the kwdefault, not time.sleep."""
    recorded: list[float] = []
    monkeypatch.setitem(resilience.call_with_retry.__kwdefaults__, "sleep", recorded.append)
    return recorded


@pytest.fixture
def offline(monkeypatch, tmp_path, sleeps):
    resilience.reset_breakers()
    for name, value in {"GUARDIAN_API_KEY": FAKE_KEYS[0], "FACTCHECK_API_KEY": FAKE_KEYS[1],
                        "GEMINI_API_KEY": FAKE_KEYS[2], "FIRECRAWL_API_KEY": FAKE_KEYS[3],
                        "NEWS_DB": str(tmp_path / "t.db"), "MAX_COST_USD_PER_RUN": "0.05",
                        "MAX_ITERATIONS": "3", "MODEL_PRIMARY": "gemini-3.6-flash", "MODEL_FALLBACK": "gemini-3.6-flash", "ENABLE_VALIDATOR": "true", "SOURCES": "guardian,factcheck"}.items():
        monkeypatch.setenv(name, value)
    yield
    resilience.reset_breakers()


def install(monkeypatch, gemini, sources=None, search_fn=None):
    """Route agents to `gemini`. Search uses `sources` through the real search_fn, or `search_fn` directly.
    The real search_fn gets budget=None because of BUG-search-1 (see test_integration_fixtures)."""
    monkeypatch.setattr(llm, "_get_client", lambda: gemini)
    if search_fn is not None:
        monkeypatch.setattr(main, "make_search_fn", lambda settings, budget, **kw: search_fn)
    else:
        monkeypatch.setattr(main, "make_search_fn",
                            lambda settings, budget, **kw: make_search_fn(settings, None, client=sources.client))


def post(body, cap=0.05):
    resp = TestClient(main.app).post("/api/check", json=body)
    events = [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]
    assert_clean_stream(resp, events, cap)
    return events


def assert_clean_stream(resp, events, cap=0.05):
    assert resp.status_code == 200
    assert events and events[-1]["type"] == "done"
    assert [e["type"] for e in events].count("done") == 1
    terminal = [e for e in events if e["type"] in ("verdict", "error")]
    assert len(terminal) == 1
    assert events.index(terminal[0]) == len(events) - 2
    for secret in ("Traceback", 'File "'):
        assert secret not in resp.text
    assert not KEY_RE.search(resp.text)
    assert not any(key in resp.text for key in FAKE_KEYS)
    assert events[-1]["cost_usd"] <= cap


def verdict_of(events):
    return next(e for e in events if e["type"] == "verdict")["report"]


def error_of(events):
    return next(e for e in events if e["type"] == "error")


def visible_text(events):
    """All string values the user could see, without JSON keys, URLs-as-data or the fixed disclaimer."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in ("disclaimer", "evidence"):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            out.append(node)

    walk(events)
    return " ".join(out).lower()


class UpstreamError(Exception):
    """Looks like google-genai errors.APIError: carries an int `code`."""

    def __init__(self, code):
        super().__init__(f"upstream {code}")
        self.code = code


def raiser(exc):
    def fail(contents):
        raise exc
    return fail


def fresh_queries():
    n = iter(range(100))
    return lambda contents: verify_json("insufficient", [f"fresh query {next(n)} words"])


@pytest.fixture
def run(offline, monkeypatch):
    def go(gemini, sources=None, body=None):
        install(monkeypatch, gemini, sources or Sources())
        return post(body or {"kind": "text", "text": "Sweden banned cash."})
    return go


# ------------------------------------------------------------------ Guardian down

def test_guardian_503_retries_three_times_per_search_and_ends_unverifiable(run, sleeps):
    sources = Sources(guardian=503)
    events = run(default_gemini(verify=fresh_queries()), sources)
    assert sources.hits["guardian"] == 9
    assert len(sleeps) == 6
    assert verdict_of(events)["claims"][0]["label"] == "UNVERIFIABLE"


def test_guardian_circuit_opens_after_three_exhausted_searches(run):
    sources = Sources(guardian=503)
    run(default_gemini(verify=fresh_queries()), sources)
    before = sources.hits["guardian"]
    run(default_gemini(verify=fresh_queries()), sources)
    assert sources.hits["guardian"] == before


def test_guardian_401_is_not_retried(run, sleeps):
    sources = Sources(guardian=401)
    run(default_gemini(verify=fresh_queries()), sources)
    assert sources.hits["guardian"] == 3
    assert sleeps == []


def test_guardian_outage_is_named_in_the_stream(run):
    events = run(default_gemini(verify=fresh_queries()), Sources(guardian=503))
    assert "guardian" in visible_text(events)


# ------------------------------------------------------------------ Fact Check down

def test_factcheck_429_retries_three_times_and_guardian_still_answers(run, sleeps):
    sources = Sources(factcheck=429)
    events = run(default_gemini(), sources)
    assert sources.hits["factcheck"] == 3
    assert len(sleeps) == 2
    claim = verdict_of(events)["claims"][0]
    assert claim["label"] != "UNVERIFIABLE"
    assert claim["confidence"] <= 0.70


def test_factcheck_outage_is_named_in_the_stream(run):
    events = run(default_gemini(), Sources(factcheck=429))
    assert "fact check" in visible_text(events) or "factcheck" in visible_text(events)


# ------------------------------------------------------------------ Gemini failures

def test_gemini_timeout_is_retried_then_friendly_error(run, sleeps):
    gemini = default_gemini(extract=raiser(httpx.ReadTimeout("timed out")))
    events = run(gemini)
    assert gemini.calls["extract"] == 3
    assert len(sleeps) == 2
    err = error_of(events)
    assert err["code"] == "internal" and err["message"] == INTERNAL_MESSAGE


def test_gemini_circuit_opens_after_three_failed_runs(run):
    gemini = default_gemini(extract=raiser(httpx.ReadTimeout("timed out")))
    for _ in range(3):
        run(gemini)
    assert gemini.calls["extract"] == 9
    events = run(gemini)
    assert gemini.calls["extract"] == 9
    assert error_of(events)["message"] == INTERNAL_MESSAGE


def test_gemini_429_is_retried(run):
    gemini = default_gemini(extract=raiser(UpstreamError(429)))
    run(gemini)
    assert gemini.calls["extract"] == 3


def test_gemini_400_is_not_retried(run, sleeps):
    gemini = default_gemini(extract=raiser(UpstreamError(400)))
    run(gemini)
    assert gemini.calls["extract"] == 1
    assert sleeps == []


def test_gemini_timeout_at_verdict_leaves_claim_unverifiable_not_crashed(run):
    gemini = default_gemini(verdict=raiser(httpx.ReadTimeout("timed out")))
    events = run(gemini)
    assert gemini.calls["verdict"] == 3
    assert verdict_of(events)["claims"][0]["label"] == "UNVERIFIABLE"


def test_malformed_json_from_verdict_is_tried_twice_without_backoff(run, sleeps):
    gemini = default_gemini(verdict="not json {")
    events = run(gemini)
    assert gemini.calls["verdict"] == 2
    assert sleeps == []
    assert verdict_of(events)["claims"][0]["label"] == "UNVERIFIABLE"


def test_malformed_json_from_extraction_gives_friendly_error(run):
    gemini = default_gemini(extract="<html>oops</html>")
    events = run(gemini)
    assert gemini.calls["extract"] == 2
    assert error_of(events)["message"] == INTERNAL_MESSAGE


def test_generic_exception_mid_run_is_not_retried_and_claim_is_unverifiable(run):
    gemini = default_gemini(verdict=raiser(RuntimeError("kaboom")))
    events = run(gemini)
    assert gemini.calls["verdict"] == 1
    claim = verdict_of(events)["claims"][0]
    assert claim["label"] == "UNVERIFIABLE"
    assert any(e["type"] == "trace" and e["status"] == "failed" for e in events)


def test_exception_text_with_a_key_does_not_reach_the_stream(run):
    leaky = RuntimeError("request failed: https://x.test/?api-key=AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE12345")
    events = run(default_gemini(verdict=raiser(leaky)))
    assert "AIzaSyFAKE" not in json.dumps(events)


# ------------------------------------------------------------------ everything down

def test_every_source_down_is_unverifiable_with_low_confidence(run):
    sources = Sources(guardian=503, factcheck=503)
    events = run(default_gemini(verify=fresh_queries()), sources)
    report = verdict_of(events)
    assert report["overall_label"] == "UNVERIFIABLE"
    assert report["claims"][0]["confidence"] <= 0.40
    assert sources.hits["guardian"] == 9 and sources.hits["factcheck"] == 9


def test_every_source_down_and_gemini_down_still_ends_with_done(run):
    gemini = default_gemini(extract=raiser(httpx.ReadTimeout("timed out")))
    events = run(gemini, Sources(guardian=503, factcheck=503))
    assert events[-1]["type"] == "done" and error_of(events)["code"] == "internal"
