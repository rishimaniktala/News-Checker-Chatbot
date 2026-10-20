"""Model fallback matrix through the real app. Also holds the v2 fakes the other test_v2_* files import."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app import llm, main, resilience
from app.prompts import (
    EXTRACTION_SYSTEM_PROMPT, OCR_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, VERDICT_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT,
)
from app.schemas import EvidenceItem, FactCheckReview, RankedEvidence
from test_failure_injection import (
    PASSAGE, QUOTE, UpstreamError, claim_json, extraction_json, error_of, offline, post, sleeps, verdict_of,
    verify_json,
)

PRIMARY, BACKUP = "gemini-3.6-flash", "gemini-3.5-flash-lite"
ROLE_OF = {EXTRACTION_SYSTEM_PROMPT: "extract", VERDICT_SYSTEM_PROMPT: "judge", OCR_SYSTEM_PROMPT: "ocr",
           REVIEW_SYSTEM_PROMPT: "review", VERIFY_SYSTEM_PROMPT: "verify"}


def component(name="Sweden banned cash", status="contradicted", ids=("E1",), kind="action"):
    return {"name": name, "kind": kind, "status": status, "evidence_ids": list(ids)}


def judge_json(label="FALSE", components=None, quote=QUOTE, stance="refutes", cid="c1", answer="No.", cited="E1"):
    comps = [component()] if components is None else components
    return json.dumps({"claim_id": cid, "label": label, "confidence": 0.9, "answer": answer, "reasoning": "Because.",
                       "citations": [{"evidence_id": cited, "quote": quote, "stance": stance}] if quote else [],
                       "components": comps})


class V2Gemini:
    """genai.Client stand-in that knows roles and models.

    A handler is a str, an Exception to raise, a callable(contents), or a list consumed in order (last repeats).
    `by_model` overrides every handler for one model, so "primary is down" is one line."""

    def __init__(self, tokens=(1000, 200), by_model=None, **handlers):
        self.handlers = {"extract": extraction_json(claim_json()), "verify": verify_json(), "judge": judge_json(),
                         "review": judge_json(), "ocr": json.dumps({"text": "", "context_note": "x", "is_legible": False})}
        self.handlers.update(handlers)
        self.by_model, self.tokens = dict(by_model or {}), tokens
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[tuple[str, object]] = []
        self.models = self

    def n(self, role=None, model=None):
        return sum((role in (None, r)) and (model in (None, m)) for r, m in self.calls)

    def generate_content(self, model, contents, config):
        role = ROLE_OF[config.system_instruction]
        self.calls.append((role, model))
        self.prompts.append((role, contents))
        handler = self.by_model.get(model, self.handlers[role])
        if isinstance(handler, list):
            handler = handler.pop(0) if len(handler) > 1 else handler[0]
        if isinstance(handler, Exception):
            raise handler
        text = handler(contents) if callable(handler) else handler
        return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
            prompt_token_count=self.tokens[0], candidates_token_count=self.tokens[1]))


def item(i=1, url="https://www.theguardian.com/world/sweden-cash", passage=PASSAGE, title="Sweden and cash",
         source="The Guardian", published="2024-03-12T14:05:00Z"):
    return EvidenceItem(id=f"E{i}", url=url, title=title, passage=passage, rerank_score=0.8, source_name=source,
                        published_at=published)


def review(i=1, rating="False", reviewed="Sweden banned cash", score=0.9, publisher="Snopes", url="https://snopes.com/x"):
    return FactCheckReview(id=f"F{i}", publisher=publisher, url=url, claim_reviewed=reviewed, raw_rating=rating,
                           match_score=score)


def fixed_search(guardian=None, factchecks=None, notes=()):
    """A search_fn returning the same evidence every round, with optional 'source unavailable' notes."""
    def search(claim, queries, round_no):
        return RankedEvidence(claim_id=claim.id, attempt=round_no,
                              guardian=[g.model_copy() for g in (guardian if guardian is not None else [item()])],
                              factchecks=[f.model_copy() for f in (factchecks or [])])
    search.unavailable = list(notes)
    return search


@pytest.fixture
def v2(offline, monkeypatch):
    """Both models configured. Returns go(gemini, search_fn=None, body=None) -> stream events."""
    monkeypatch.setenv("MODEL_FALLBACK", BACKUP)
    monkeypatch.setenv("CACHE_TTL_HOURS", "0")

    def go(gemini, search_fn=None, body=None):
        monkeypatch.setattr(llm, "_get_client", lambda: gemini)
        sfn = search_fn or fixed_search()
        monkeypatch.setattr(main, "make_search_fn", lambda settings, **kw: sfn)
        return post(body or {"kind": "text", "text": "Sweden banned cash."})
    return go


def done_of(events):
    return events[-1]


def trace_messages(events):
    return [e["message"] for e in events if e["type"] == "trace"]


# ------------------------------------------------------------------ primary down, backup answers

DOWN = {"429": UpstreamError(429), "503": UpstreamError(503), "timeout": httpx.ReadTimeout("t"),
        "malformed": "not json {"}


@pytest.mark.parametrize("how", DOWN)
def test_primary_failure_still_ends_with_a_verdict(v2, how):
    events = v2(V2Gemini(by_model={PRIMARY: DOWN[how]}))
    assert verdict_of(events)["claims"][0]["label"] == "FALSE"


@pytest.mark.parametrize("how", DOWN)
def test_primary_failure_announces_the_backup_model(v2, how):
    events = v2(V2Gemini(by_model={PRIMARY: DOWN[how]}))
    assert any("backup model" in m for m in trace_messages(events))


@pytest.mark.parametrize("how", DOWN)
def test_primary_failure_sets_fallback_used_and_lists_the_backup(v2, how):
    done = done_of(v2(V2Gemini(by_model={PRIMARY: DOWN[how]})))
    assert done["fallback_used"] is True and BACKUP in done["models_used"]


@pytest.mark.parametrize("how", DOWN)
def test_primary_failure_marks_the_claim_report(v2, how):
    claim = verdict_of(v2(V2Gemini(by_model={PRIMARY: DOWN[how]})))["claims"][0]
    assert claim["fallback_used"] is True and claim["model_used"] == BACKUP
    assert claim["confidence_factors"]["model_quality"] < 1.0


def test_healthy_primary_never_touches_the_backup(v2):
    gemini = V2Gemini()
    done = done_of(v2(gemini))
    assert gemini.n(model=BACKUP) == 0
    assert done["fallback_used"] is False and done["models_used"] == [PRIMARY]


def test_backup_announcement_is_sent_once_per_backup_model(v2):
    events = v2(V2Gemini(by_model={PRIMARY: UpstreamError(503)}))
    assert sum("backup model" in m for m in trace_messages(events)) == 1


# ------------------------------------------------------------------ 401 and 400: no fallback

@pytest.mark.parametrize("role", ["extract", "judge"])
def test_401_gives_a_friendly_outcome_and_no_backup_call(v2, role):
    gemini = V2Gemini(**{role: UpstreamError(401)})
    events = v2(gemini)
    assert gemini.n(model=BACKUP) == 0
    assert events[-1]["type"] == "done"


def test_401_at_the_judge_does_not_show_the_raw_upstream_error(v2):
    events = v2(V2Gemini(judge=UpstreamError(401)))
    failed = [e["message"] for e in events if e["type"] == "trace" and e["status"] == "failed"]
    assert failed and not any("UpstreamError" in m or "upstream 401" in m for m in failed)


def test_401_at_extraction_is_the_internal_error_message(v2):
    events = v2(V2Gemini(extract=UpstreamError(401)))
    assert error_of(events)["message"] == main.INTERNAL_MESSAGE


def test_400_is_not_sent_to_the_backup(v2):
    gemini = V2Gemini(extract=UpstreamError(400))
    v2(gemini)
    assert gemini.n(model=BACKUP) == 0


# ------------------------------------------------------------------ both down

def test_both_models_down_at_the_judge_is_unverifiable_not_a_crash(v2):
    events = v2(V2Gemini(judge=UpstreamError(503)))
    claim = verdict_of(events)["claims"][0]
    assert claim["label"] == "UNVERIFIABLE"


def test_both_models_down_at_the_judge_leaves_a_failed_trace(v2):
    events = v2(V2Gemini(judge=UpstreamError(503)))
    assert any(e["type"] == "trace" and e["status"] == "failed" for e in events)


def test_both_models_down_at_extraction_is_a_friendly_error_and_done(v2):
    events = v2(V2Gemini(extract=UpstreamError(503)))
    assert error_of(events)["message"] == main.INTERNAL_MESSAGE and events[-1]["type"] == "done"


def test_both_models_return_garbage_is_unverifiable(v2):
    events = v2(V2Gemini(judge="nope"))
    assert verdict_of(events)["claims"][0]["label"] == "UNVERIFIABLE"


# ------------------------------------------------------------------ breakers

@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setitem(resilience.call_with_retry.__kwdefaults__, "clock", lambda: now[0])
    return now


def test_primary_breaker_opens_after_three_failed_calls_and_backup_stays_closed(v2, clock):
    v2(V2Gemini(by_model={PRIMARY: UpstreamError(503)}))
    assert resilience._breakers[llm.PRIMARY][0] >= 3
    assert llm.FALLBACK not in resilience._breakers


def test_open_primary_breaker_skips_the_primary_on_the_next_run(v2, clock):
    gemini = V2Gemini(by_model={PRIMARY: UpstreamError(503)})
    v2(gemini)
    before = gemini.n(model=PRIMARY)
    v2(gemini)
    assert gemini.n(model=PRIMARY) == before


def test_open_primary_breaker_still_gives_a_verdict_from_the_backup(v2, clock):
    gemini = V2Gemini(by_model={PRIMARY: UpstreamError(503)})
    v2(gemini)
    assert verdict_of(v2(gemini))["claims"][0]["label"] == "FALSE"


def test_primary_breaker_recovers_after_the_cooldown(v2, clock):
    gemini = V2Gemini(by_model={PRIMARY: UpstreamError(503)})
    v2(gemini)
    gemini.by_model.clear()
    clock[0] += resilience.COOLDOWN_SECONDS + 1
    done = done_of(v2(gemini))
    assert done["fallback_used"] is False and done["models_used"] == [PRIMARY]


def test_primary_breaker_stays_open_inside_the_cooldown(v2, clock):
    gemini = V2Gemini(by_model={PRIMARY: UpstreamError(503)})
    v2(gemini)
    gemini.by_model.clear()
    clock[0] += resilience.COOLDOWN_SECONDS - 5
    assert done_of(v2(gemini))["fallback_used"] is True


def test_fallback_breaker_is_independent_of_the_primary(v2, clock):
    gemini = V2Gemini(judge=UpstreamError(503))
    v2(gemini)
    assert resilience._breakers[llm.FALLBACK][0] >= 1
    assert resilience._breakers[llm.PRIMARY][0] >= 1
    assert gemini.n("extract", BACKUP) == 0
