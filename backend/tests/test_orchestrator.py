from dataclasses import replace

import pytest

from app import orchestrator
from app.agents import AgentError, EvidenceCheck, EvidenceDecision
from app.budget import RunBudget
from app.config import Settings
from app.schemas import (
    Citation, Claim, ClaimExtraction, ClaimVerdict, EvidenceItem, InputType,
    NormalizedInput, RankedEvidence, Stance, VerdictLabel,
)

SETTINGS = Settings("m", True, ("guardian",), 3, 1.0)
PASSAGE = "Sweden has not banned cash. Shops may refuse cash."


def make_claim(cid="c1", queries=("sweden cash ban",)):
    return Claim(id=cid, text="Sweden banned cash.", checkworthy=True, search_queries=list(queries))


def make_budget(cap=1.0):
    return RunBudget(cap, 3)


def good_verdict(claim, quote="Sweden has not banned cash"):
    return ClaimVerdict(claim_id=claim.id, label=VerdictLabel.FALSE, confidence=0.9, answer="No.",
                        reasoning="Because.", citations=[Citation(evidence_id="E1", quote=quote, stance=Stance.REFUTES)])


def search(claim, queries, round_no):
    item = EvidenceItem(id="E1", url="https://x.test/a", title="t", passage=PASSAGE, rerank_score=0.8)
    return RankedEvidence(claim_id=claim.id, attempt=round_no, guardian=[item])


def check(decision, queries=()):
    return lambda claim, ev, tried: EvidenceCheck(claim_id=claim.id, decision=decision, relevant_ids=["E1"],
                                                  reason="r", new_search_queries=list(queries))


@pytest.fixture
def agents(monkeypatch):
    """Sufficient evidence and a valid verdict by default; tests override pieces."""
    calls = {"search": 0, "verdict": 0}
    monkeypatch.setattr(orchestrator, "check_evidence",
                        lambda c, ev, tried: EvidenceCheck(claim_id=c.id, decision=EvidenceDecision.SUFFICIENT,
                                                           relevant_ids=["E1"], reason="ok"))

    def verdict(c, ev, previous_failure=None):
        calls["verdict"] += 1
        return good_verdict(c)

    def counting_search(c, q, n):
        calls["search"] += 1
        return search(c, q, n)

    monkeypatch.setattr(orchestrator, "give_verdict", verdict)
    calls["search_fn"] = counting_search
    return calls


def run_claim(agents, settings=SETTINGS, budget=None, claim=None):
    events = []
    report = orchestrator.check_claim(claim or make_claim(), agents["search_fn"], settings,
                                      budget or make_budget(), events.append, "r1")
    return report, events


def test_happy_path(agents):
    report, events = run_claim(agents)
    assert report.label == VerdictLabel.FALSE
    assert all(e["type"] == "trace" for e in events)


def unique_queries(monkeypatch, decision=EvidenceDecision.INSUFFICIENT):
    n = iter(range(100))
    monkeypatch.setattr(orchestrator, "check_evidence", lambda c, ev, tried: EvidenceCheck(
        claim_id=c.id, decision=decision, reason="no", new_search_queries=[f"fresh query {next(n)}"]))


def test_search_rounds_capped_at_three(agents, monkeypatch):
    unique_queries(monkeypatch)
    report, _ = run_claim(agents)
    assert agents["search"] == 3
    assert report.label == VerdictLabel.UNVERIFIABLE


def test_max_iterations_one_is_single_shot(agents, monkeypatch):
    unique_queries(monkeypatch)
    run_claim(agents, replace(SETTINGS, max_iterations=1))
    assert agents["search"] == 1
    monkeypatch.setattr(orchestrator, "give_verdict",
                        lambda c, ev, previous_failure=None: agents.__setitem__("verdict", agents["verdict"] + 1)
                        or good_verdict(c, "not in the passage"))
    agents["verdict"] = 0
    monkeypatch.setattr(orchestrator, "check_evidence", check(EvidenceDecision.SUFFICIENT))
    report, _ = run_claim(agents, replace(SETTINGS, max_iterations=1))
    assert agents["verdict"] == 1
    assert report.label == VerdictLabel.UNVERIFIABLE


def test_validator_attempts_capped_at_three_then_unverifiable(agents, monkeypatch):
    monkeypatch.setattr(orchestrator, "give_verdict", lambda c, ev, previous_failure=None: (
        agents.__setitem__("verdict", agents["verdict"] + 1), good_verdict(c, "made up quote"))[1])
    report, events = run_claim(agents)
    assert agents["verdict"] == 3
    assert report.label == VerdictLabel.UNVERIFIABLE
    assert [e["status"] for e in events if e["step"] == "validate"] == ["retry", "retry", "failed"]


def test_rationale_problems_count_as_failure_and_feed_retry_hint(agents, monkeypatch):
    hints = []
    monkeypatch.setattr(orchestrator, "check_rationale", lambda v, ev, text="": ["answer contradicts label"])
    monkeypatch.setattr(orchestrator, "give_verdict", lambda c, ev, previous_failure=None: (
        hints.append(previous_failure), good_verdict(c))[1])
    report, _ = run_claim(agents)
    assert len(hints) == 3
    assert "answer contradicts label" in hints[1]
    assert report.label == VerdictLabel.UNVERIFIABLE


def test_cost_cap_stops_the_loop(agents, monkeypatch):
    budget = make_budget(cap=0.0)
    report, events = run_claim(agents, budget=budget)
    assert agents["search"] == 0
    assert report.label == VerdictLabel.UNVERIFIABLE
    assert any(e["status"] == "failed" and "Cost cap" in e["message"] for e in events)


def test_repeated_query_is_blocked(agents, monkeypatch):
    budget = make_budget()
    budget.register_query("Sweden cash ban!", "c1")
    report, events = run_claim(agents, budget=budget)
    assert agents["search"] == 0
    assert any("No new queries" in e["message"] for e in events)


def test_validator_toggle(agents, monkeypatch):
    monkeypatch.setattr(orchestrator, "give_verdict",
                        lambda c, ev, previous_failure=None: good_verdict(c, "made up quote"))
    report, events = run_claim(agents, replace(SETTINGS, enable_validator=False))
    assert report.label == VerdictLabel.FALSE
    assert any("Validator disabled" in e["message"] for e in events)


def extraction(*claims):
    return lambda inp: ClaimExtraction(claims=list(claims))


def run_input(emit=None):
    inp = NormalizedInput(input_type=InputType.TEXT, text="x")
    return orchestrator.check_input(inp, search, SETTINGS, make_budget(), emit or (lambda e: None), "r1")


def test_one_claim_raising_does_not_stop_others(agents, monkeypatch):
    monkeypatch.setattr(orchestrator, "extract_claims", extraction(make_claim("c1"), make_claim("c2", ("other q",))))

    def verdict(c, ev, previous_failure=None):
        if c.id == "c1":
            raise RuntimeError("boom")
        return good_verdict(c)

    monkeypatch.setattr(orchestrator, "give_verdict", verdict)
    events = []
    report = run_input(events.append)
    assert [c.label for c in report.claims] == [VerdictLabel.UNVERIFIABLE, VerdictLabel.FALSE]
    assert any(e["status"] == "failed" and "boom" in e["message"] and e["claim_id"] == "c1" for e in events)


def test_malformed_json_agent_error_becomes_unverifiable(agents, monkeypatch):
    monkeypatch.setattr(orchestrator, "extract_claims", extraction(make_claim()))

    def bad(*a, **k):
        raise AgentError("ClaimVerdict: model gave no valid output")

    monkeypatch.setattr(orchestrator, "give_verdict", bad)
    events = []
    report = run_input(events.append)
    assert report.claims[0].label == VerdictLabel.UNVERIFIABLE
    assert any(e["status"] == "failed" and "AgentError" in e["message"] for e in events)


# ------------------------------------------------------------- v2: components and second opinion

from app import llm  # noqa: E402
from app.schemas import ComponentCheck, ComponentStatus, Step  # noqa: E402

QUOTE = "Sweden has not banned cash"


def comp(status, ids=("E1",), name="part"):
    return ComponentCheck(name=name, status=status, evidence_ids=list(ids))


def v2_verdict(claim, label, components, confidence=0.9):
    stance = Stance.REFUTES if label == VerdictLabel.FALSE else Stance.SUPPORTS
    cites = [] if label == VerdictLabel.UNVERIFIABLE else [Citation(evidence_id="E1", quote=QUOTE, stance=stance)]
    return ClaimVerdict(claim_id=claim.id, label=label, confidence=confidence, answer="Yes, per the sources.",
                        reasoning="r", citations=cites, components=components)


def stub_judge(monkeypatch, agents, first, review=None, review_error=None):
    calls = {"review": 0}
    monkeypatch.setattr(orchestrator, "give_verdict", lambda c, ev, previous_failure=None: first)

    def give_review(c, ev, v, derived):
        calls["review"] += 1
        if review_error:
            raise review_error
        return review

    monkeypatch.setattr(orchestrator, "give_review", give_review)
    return calls


def test_consistent_judge_gets_no_second_opinion(agents, monkeypatch):
    first = v2_verdict(make_claim(), VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED)])
    calls = stub_judge(monkeypatch, agents, first)
    report, events = run_claim(agents)
    assert calls["review"] == 0
    assert report.label == VerdictLabel.TRUE
    assert report.confidence_factors["judge_agreement"] == 1.0
    assert [c.status for c in report.components] == [ComponentStatus.SUPPORTED]
    assert not any(e["step"] == Step.REVIEW.value for e in events)


def test_second_opinion_settles_a_label_mismatch(agents, monkeypatch):
    claim = make_claim()
    first = v2_verdict(claim, VerdictLabel.TRUE, [comp(ComponentStatus.CONTRADICTED)])
    fixed = v2_verdict(claim, VerdictLabel.FALSE, [comp(ComponentStatus.CONTRADICTED)])
    calls = stub_judge(monkeypatch, agents, first, review=fixed)
    report, events = run_claim(agents)
    assert calls["review"] == 1
    assert report.label == VerdictLabel.FALSE
    assert report.confidence_factors["judge_agreement"] == 0.5
    assert [e["status"] for e in events if e["step"] == Step.REVIEW.value] == ["started", "completed"]


def test_unresolved_mismatch_takes_the_more_cautious_label_and_marks_agreement_low(agents, monkeypatch):
    claim = make_claim()
    first = v2_verdict(claim, VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED), comp(ComponentStatus.UNKNOWN, ())])
    still_wrong = v2_verdict(claim, VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED), comp(ComponentStatus.UNKNOWN, ())])
    stub_judge(monkeypatch, agents, first, review=still_wrong)
    report, _ = run_claim(agents)
    assert report.label == VerdictLabel.UNVERIFIABLE
    assert report.confidence_factors["judge_agreement"] == 0.0
    assert report.answer.startswith("I couldn't confirm")


def test_review_with_invented_quote_is_not_trusted(agents, monkeypatch):
    claim = make_claim()
    first = v2_verdict(claim, VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED), comp(ComponentStatus.CONTRADICTED, ("E1",))])
    bad = v2_verdict(claim, VerdictLabel.MISLEADING, first.components)
    bad.citations[0].quote = "text that is not in the passage"
    stub_judge(monkeypatch, agents, first, review=bad)
    report, _ = run_claim(agents)
    assert report.label == VerdictLabel.MISLEADING
    assert report.confidence_factors["judge_agreement"] == 0.0


def test_review_failure_falls_back_and_never_leaks_a_key(agents, monkeypatch):
    claim = make_claim()
    first = v2_verdict(claim, VerdictLabel.TRUE, [comp(ComponentStatus.UNKNOWN, ())])
    stub_judge(monkeypatch, agents, first, review_error=RuntimeError("boom AIzaSyA1234567890123456789012345"))
    report, events = run_claim(agents)
    assert report.label == VerdictLabel.UNVERIFIABLE
    assert "AIza" not in str(events)


def test_v1_style_verdict_without_components_skips_review(agents, monkeypatch):
    calls = stub_judge(monkeypatch, agents, good_verdict(make_claim()))
    report, _ = run_claim(agents)
    assert calls["review"] == 0 and report.label == VerdictLabel.FALSE and report.components == []


def test_report_records_model_fallback_and_independent_sources(agents, monkeypatch):
    first = v2_verdict(make_claim(), VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED)])
    stub_judge(monkeypatch, agents, first)
    log = llm.begin_run()
    log.calls += [llm.CallRecord("judge", "gemini-3.5-flash-lite", fallback_used=True)]
    report, _ = run_claim(agents)
    assert report.model_used == "gemini-3.5-flash-lite" and report.fallback_used
    assert report.independent_sources == 1
    assert report.confidence_factors["model_quality"] < 1.0


def test_trace_names_counts_per_source(agents, monkeypatch):
    stub_judge(monkeypatch, agents, v2_verdict(make_claim(), VerdictLabel.TRUE, [comp(ComponentStatus.SUPPORTED)]))
    fn = agents["search_fn"]
    fn.stats = {"guardian": 5, "web": 3, "factcheck": 1}
    _, events = run_claim(agents)
    assert any(e["message"] == "Round 1 sources: guardian 5, web 3, factcheck 1" for e in events)


def test_final_report_records_prompt_version_and_models(monkeypatch):
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[]))
    log = llm.begin_run()
    log.calls.append(llm.CallRecord("extract", "gemini-3.6-flash"))
    inp = NormalizedInput(input_type=InputType.TEXT, text="t")
    out = orchestrator.check_input(inp, search, SETTINGS, make_budget(), lambda e: None, "r1")
    assert out.prompt_version == orchestrator.PROMPT_VERSION and out.models_used == ["gemini-3.6-flash"]
