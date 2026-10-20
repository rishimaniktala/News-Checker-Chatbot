"""Real failures from earlier runs. The model is replaced by the reply a good (or a bad) judge would give."""

from datetime import datetime

import pytest

from app import orchestrator
from app.agents import EvidenceCheck, EvidenceDecision
from app.budget import RunBudget
from app.config import Settings
from app.rules import compute_consensus
from app.schemas import (
    Citation, Claim, ClaimExtraction, ClaimVerdict, ComponentCheck, ComponentStatus as S, EvidenceItem,
    FactCheckReview, InputType, NormalizedInput, RankedEvidence, Stance, VerdictLabel as L,
)

SETTINGS = Settings("m", True, ("guardian",), 3, 1.0)


def item(eid, passage, published):
    return EvidenceItem(id=eid, url=f"https://x.test/{eid}", title="t", passage=passage, rerank_score=0.8,
                        published_at=datetime.fromisoformat(published))


def cite(eid, quote, stance=Stance.SUPPORTS):
    return Citation(evidence_id=eid, quote=quote, stance=stance)


def comp(name, status, *ids):
    return ComponentCheck(name=name, status=status, evidence_ids=list(ids))


def run(monkeypatch, text, evidence, first, review=None):
    claim = Claim(id="c1", text=text, checkworthy=True, search_queries=["q"])
    reviews = []
    monkeypatch.setattr(orchestrator, "check_evidence", lambda c, ev, tried: EvidenceCheck(
        claim_id=c.id, decision=EvidenceDecision.SUFFICIENT, relevant_ids=sorted(ev.valid_ids), reason="ok"))
    monkeypatch.setattr(orchestrator, "give_verdict", lambda c, ev, previous_failure=None: first)

    def give_review(c, ev, v, derived):
        reviews.append(derived)
        return review or v

    monkeypatch.setattr(orchestrator, "give_review", give_review)
    report = orchestrator.check_claim(claim, lambda c, q, n: evidence, SETTINGS, RunBudget(1.0, 3), lambda e: None, "r1")
    return report, reviews


def verdict(label, citations, components, answer="a"):
    return ClaimVerdict(claim_id="c1", label=label, confidence=0.9, answer=answer, reasoning="r",
                        citations=citations, components=components)


def test_sweden_nato_topic_only_evidence_is_not_a_verdict_on_the_year(monkeypatch):
    topic_only = RankedEvidence(claim_id="c1", guardian=[
        item("E1", "Sweden is a member of Nato and hosts allied exercises.", "2025-02-01T00:00:00")])
    overconfident = verdict(L.TRUE, [cite("E1", "Sweden is a member of Nato")],
                            [comp("Sweden joined NATO", S.SUPPORTED, "E1"), comp("in 2024", S.UNKNOWN)])
    report, reviews = run(monkeypatch, "Sweden joined NATO in 2024.", topic_only, overconfident)
    assert reviews == [L.UNVERIFIABLE]
    assert report.label == L.UNVERIFIABLE


def test_sweden_nato_with_dated_evidence_is_true(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[
        item("E2", "Sweden became Nato's 32nd member after depositing its papers.", "2024-03-11T00:00:00")])
    good = verdict(L.TRUE, [cite("E2", "Sweden became Nato's 32nd member")],
                   [comp("Sweden joined NATO", S.SUPPORTED, "E2"), comp("in 2024", S.SUPPORTED, "E2")])
    report, reviews = run(monkeypatch, "Sweden joined NATO in 2024.", ev, good)
    assert report.label == L.TRUE and not reviews and report.independent_sources == 1


def test_bank_of_england_2024_cut_does_not_confirm_august_2023(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[
        item("E1", "The Bank cut rates to 5% from 5.25%, the first cut in four years.", "2024-08-01T00:00:00")])
    confused = verdict(L.TRUE, [cite("E1", "from 5.25%")],
                       [comp("rate was 5.25%", S.SUPPORTED, "E1"), comp("in August 2023", S.CONTRADICTED, "E1")])
    report, reviews = run(monkeypatch, "The Bank of England held rates at 5.25% in August 2023.", ev, confused)
    assert reviews == [L.MISLEADING]
    assert report.label == L.MISLEADING


def test_unrelated_musk_google_fact_check_does_not_flip_a_true_claim():
    ev = RankedEvidence(claim_id="c1", guardian=[item("E1", "Musk completed his purchase of Twitter.", "2022-10-28T00:00:00")],
                        factchecks=[FactCheckReview(id="F1", publisher="P", url="https://x/f", claim_reviewed="Elon Musk bought Google",
                                                    raw_rating="False", match_score=0.52, normalized_label=L.FALSE)])
    v = verdict(L.TRUE, [cite("E1", "Musk completed his purchase of Twitter")],
                [comp("Musk", S.SUPPORTED, "E1"), comp("bought Twitter", S.SUPPORTED, "E1")])
    result = compute_consensus(v, ev)
    assert result.final_label == L.TRUE and not result.conflict


def test_fact_check_at_077_about_a_video_does_not_flip_the_verdict():
    ev = RankedEvidence(claim_id="c1", guardian=[item("E1", "The army entered the town.", "2024-05-01T00:00:00")],
                        factchecks=[FactCheckReview(id="F1", publisher="P", url="https://x/f", claim_reviewed="A video of an army",
                                                    raw_rating="misleading", match_score=0.77, normalized_label=L.MISLEADING)])
    v = verdict(L.TRUE, [cite("E1", "The army entered the town")], [comp("army entered", S.SUPPORTED, "E1")])
    assert compute_consensus(v, ev).final_label == L.TRUE


def test_opinion_is_skipped_and_nothing_is_retrieved(monkeypatch):
    opinion = Claim(id="c1", text="Vladimir Putin is a dictator.", checkworthy=False, skip_reason="opinion")
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[opinion]))

    def boom(*a):
        raise AssertionError("retrieval must not run for an opinion")

    out = orchestrator.check_input(NormalizedInput(input_type=InputType.TEXT, text="Putin is a dictator"), boom,
                                   SETTINGS, RunBudget(1.0, 3), lambda e: None, "r1")
    assert out.overall_label == L.UNVERIFIABLE and "opinion" in out.answer and out.claims == []


def test_vaccines_autism_stance_is_never_read_as_true(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[
        item("E1", "Large studies found no link between vaccines and autism.", "2019-03-01T00:00:00")])
    misread = verdict(L.TRUE, [cite("E1", "no link between vaccines and autism")],
                      [comp("vaccines cause autism", S.CONTRADICTED, "E1")])
    report, reviews = run(monkeypatch, "Vaccines cause autism.", ev, misread)
    assert reviews == [L.FALSE]
    assert report.label == L.UNVERIFIABLE


def test_vaccines_autism_correct_reading_is_false(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[
        item("E1", "Large studies found no link between vaccines and autism.", "2019-03-01T00:00:00")])
    right = verdict(L.FALSE, [cite("E1", "no link between vaccines and autism", Stance.REFUTES)],
                    [comp("vaccines cause autism", S.CONTRADICTED, "E1")], answer="No, studies found no link.")
    report, reviews = run(monkeypatch, "Vaccines cause autism.", ev, right)
    assert report.label == L.FALSE and not reviews


def test_denying_a_plan_is_not_confirming_a_sale(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[item("E1", "The prince will not live there.", "2024-05-01T00:00:00")])
    wrong = verdict(L.TRUE, [cite("E1", "The prince will not live there")], [comp("estate is being sold", S.UNKNOWN)])
    report, _ = run(monkeypatch, "The prince is selling the estate.", ev, wrong)
    assert report.label == L.UNVERIFIABLE


def test_keys_never_appear_in_the_report_or_trace(monkeypatch):
    ev = RankedEvidence(claim_id="c1", guardian=[item("E1", "Text.", "2024-05-01T00:00:00")])
    first = verdict(L.TRUE, [cite("E1", "Text.")], [comp("part", S.UNKNOWN)])
    events = []
    monkeypatch.setattr(orchestrator, "check_evidence", lambda c, e, t: EvidenceCheck(
        claim_id=c.id, decision=EvidenceDecision.SUFFICIENT, relevant_ids=["E1"], reason="ok"))
    monkeypatch.setattr(orchestrator, "give_verdict", lambda c, e, previous_failure=None: first)

    def failing(*a):
        raise RuntimeError("https://x/?api-key=SECRET123 AIzaSyA1234567890123456789012345")

    monkeypatch.setattr(orchestrator, "give_review", failing)
    claim = Claim(id="c1", text="t", checkworthy=True, search_queries=["q"])
    report = orchestrator.check_claim(claim, lambda c, q, n: ev, SETTINGS, RunBudget(1.0, 3), events.append, "r1")
    dump = str(events) + report.model_dump_json()
    assert "SECRET123" not in dump and "AIzaSy" not in dump
