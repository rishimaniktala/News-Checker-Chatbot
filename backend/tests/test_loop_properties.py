"""Loop and cost caps hold when the fake model misbehaves forever. Real agents, real orchestrator."""

import pytest

from app import agents
from app.budget import RunBudget
from app.config import Settings
from app.run import run_check
from app.schemas import RankedEvidence
from test_failure_injection import (
    default_gemini, fresh_queries, offline, sleeps, verdict_json, verify_json,
)
from test_orchestrator import search

CLAIM_TEXT = {"kind": "text", "text": "Sweden banned cash."}
SETTINGS = Settings("gemini-2.5-flash", True, ("guardian",), 3, 1.0)
CALL_COST = (1000 * 0.30 + 200 * 2.50) / 1_000_000


@pytest.fixture
def go(offline, monkeypatch):
    def run(gemini, evidence=search, cap=1.0):
        monkeypatch.setattr(agents, "_get_client", lambda: gemini)
        searches, events = [], []

        def counting(claim, queries, n):
            searches.append(queries)
            return evidence(claim, queries, n)

        budget = RunBudget(cap, 3)
        report = run_check(dict(CLAIM_TEXT), events.append, SETTINGS, counting, budget)
        return report, events, searches, budget
    return run


def test_invalid_quote_every_time_stops_at_three_attempts(go):
    gemini = default_gemini(verdict=verdict_json(quote="a sentence nobody wrote"))
    report, events, _, _ = go(gemini)
    assert gemini.calls["verdict"] == 3
    assert report.claims[0].label.value == "UNVERIFIABLE"


def test_invalid_quote_validation_trace_shows_retry_retry_failed(go):
    gemini = default_gemini(verdict=verdict_json(quote="a sentence nobody wrote"))
    _, events, _, _ = go(gemini)
    assert [e["status"] for e in events if e["step"] == "validate"] == ["retry", "retry", "failed"]


def test_unknown_evidence_id_every_time_also_stops_at_three(go):
    bad = verdict_json().replace('"E1"', '"E99"')
    gemini = default_gemini(verdict=bad)
    report, _, _, _ = go(gemini)
    assert gemini.calls["verdict"] == 3
    assert report.claims[0].label.value == "UNVERIFIABLE"


def test_insufficient_evidence_every_time_stops_at_three_rounds(go):
    gemini = default_gemini(verify=fresh_queries())
    report, _, searches, _ = go(gemini)
    assert len(searches) == 3 and gemini.calls["verify"] == 3
    assert gemini.calls["verdict"] == 0
    assert report.claims[0].label.value == "UNVERIFIABLE"


def test_empty_search_results_every_time_stops_at_three_rounds(go):
    gemini = default_gemini(verify=fresh_queries())
    _, _, searches, _ = go(gemini, evidence=lambda c, q, n: RankedEvidence(claim_id=c.id, attempt=n))
    assert len(searches) == 3


def test_model_repeating_old_queries_ends_the_search_early(go):
    gemini = default_gemini(verify=verify_json("insufficient", ["sweden cash ban"]))
    _, _, searches, _ = go(gemini)
    assert len(searches) == 1


def test_tiny_cost_cap_stops_before_any_search(go):
    gemini = default_gemini()
    report, events, searches, budget = go(gemini, cap=CALL_COST / 2)
    assert searches == [] and gemini.calls["verify"] == 0 and gemini.calls["verdict"] == 0
    assert report.claims[0].label.value == "UNVERIFIABLE"
    assert any("Cost cap" in e["message"] for e in events)


def test_cost_cap_after_one_round_stops_the_next_round(go):
    gemini = default_gemini(verify=fresh_queries())
    _, _, searches, budget = go(gemini, cap=CALL_COST * 1.5)
    assert len(searches) == 1
    assert budget.cost_usd < CALL_COST * 3


def test_cost_cap_stops_verdict_retries(go):
    gemini = default_gemini(verdict=verdict_json(quote="a sentence nobody wrote"))
    _, _, _, budget = go(gemini, cap=CALL_COST * 3.5)
    assert gemini.calls["verdict"] < 3
    assert budget.cost_usd < CALL_COST * 6


def test_spend_never_passes_the_cap_by_more_than_one_call(go):
    cap = CALL_COST * 2.5
    gemini = default_gemini(verify=fresh_queries(), verdict=verdict_json(quote="a sentence nobody wrote"))
    _, _, _, budget = go(gemini, cap=cap)
    assert budget.cost_usd <= cap + CALL_COST
