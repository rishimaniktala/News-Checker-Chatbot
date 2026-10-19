"""Real search_fn (Guardian + Fact Check clients, rerank) on recorded-shape fixtures, fake LLM, real run_check."""

import json
import re
from pathlib import Path

import httpx
import pytest

from app import agents
from app.budget import RunBudget
from app.config import Settings
from app.retrievers.search import make_search_fn
from app.run import run_check
from test_failure_injection import (
    claim_json, default_gemini, extraction_json, offline, sleeps, verdict_json, verify_json,
)

FIX = Path(__file__).parent / "fixtures"
SETTINGS = Settings("gemini-2.5-flash", True, ("guardian", "factcheck"), 3, 0.05)
CLAIM = "The Bank of England held interest rates at 5.25%."
REQ = {"kind": "text", "text": CLAIM}


def fixture_client():
    def handler(req: httpx.Request):
        name = "guardian_search.json" if "guardian" in req.url.host else "factcheck_search.json"
        return httpx.Response(200, json=json.loads((FIX / name).read_text()))

    return httpx.Client(transport=httpx.MockTransport(handler))


def first_sentence_of_first_passage(contents):
    """Fake judge: quote the first sentence of the E1 passage straight from the prompt."""
    passage = re.search(r"\[E1\].*\npassage: (.+)", contents).group(1)
    return verdict_json(quote=passage.split(".")[0] + ".", label="TRUE").replace('"No."', '"Yes."')


def gemini():
    return default_gemini(
        extract=extraction_json(claim_json(text=CLAIM, queries=("bank of england interest rates",))),
        verdict=first_sentence_of_first_passage)


def run(monkeypatch, budget_for_search):
    monkeypatch.setattr(agents, "_get_client", lambda: gemini())
    budget = RunBudget(0.05, 3)
    search_fn = make_search_fn(SETTINGS, budget if budget_for_search else None, client=fixture_client())
    events = []
    return run_check(dict(REQ), events.append, SETTINGS, search_fn, budget), events


def quotable_texts(evidence):
    return {e.id: [e.passage] for e in evidence.guardian} | {
        f.id: [f.claim_reviewed, f.raw_rating] for f in evidence.factchecks}


def test_fixtures_give_a_validated_cited_verdict(offline, monkeypatch):
    report, events = run(monkeypatch, budget_for_search=False)
    claim = report.claims[0]
    assert claim.label.value != "UNVERIFIABLE"
    assert claim.citations
    assert [e["payload"]["passed"] for e in events if e["step"] == "validate"] == [True]


def test_every_quote_is_a_verbatim_substring_of_a_retrieved_passage(offline, monkeypatch):
    report, _ = run(monkeypatch, budget_for_search=False)
    claim = report.claims[0]
    texts = quotable_texts(claim.evidence)
    for citation in claim.citations:
        assert any(citation.quote in t for t in texts[citation.evidence_id])


def test_retrieved_passages_come_from_the_fixture_not_elsewhere(offline, monkeypatch):
    report, _ = run(monkeypatch, budget_for_search=False)
    body = json.dumps(json.loads((FIX / "guardian_search.json").read_text()))
    for item in report.claims[0].evidence.guardian:
        assert item.passage.split(".")[0] in body


def test_report_never_contains_the_api_keys(offline, monkeypatch):
    report, events = run(monkeypatch, budget_for_search=False)
    blob = report.model_dump_json() + json.dumps(events)
    assert "fake-guardian-key-0001" not in blob and "fake-factcheck-key-0002" not in blob


@pytest.mark.xfail(strict=True, reason="BUG-search-1: orchestrator.py:89 and search.py:36 both call budget.register_query, so with the budget main.py passes in, every query is seen as a repeat and no source is ever called")
def test_search_fn_given_the_run_budget_still_retrieves(offline, monkeypatch):
    report, _ = run(monkeypatch, budget_for_search=True)
    assert report.claims[0].evidence.guardian
