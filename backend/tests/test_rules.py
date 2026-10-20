import pytest

from app.rules import check_rationale, validate_verdict
from app.schemas import (
    Citation, CitationFailure, ClaimVerdict, EvidenceItem, FactCheckReview,
    RankedEvidence, Stance, VerdictLabel,
)

URL = "https://www.theguardian.com/world/2024/jan/01/story"
PASSAGE = "Unemployment fell to 5% in 2024 after 1,200,000 jobs were added, the ministry said."


def evidence():
    return RankedEvidence(
        claim_id="c1",
        guardian=[EvidenceItem(id="E1", url=URL, title="Jobs report", passage=PASSAGE, rerank_score=0.9)],
        factchecks=[FactCheckReview(
            id="F1", publisher="Pub", url="https://factcheck.example/a",
            claim_reviewed="Jobs rose by 2 million", raw_rating="False", match_score=0.8)],
    )


def verdict(answer="Yes.", reasoning="Unemployment fell.", label=VerdictLabel.TRUE, quote="fell to 5%", eid="E1"):
    return ClaimVerdict(
        claim_id="c1", label=label, confidence=0.8, answer=answer, reasoning=reasoning,
        citations=[Citation(evidence_id=eid, quote=quote, stance=Stance.SUPPORTS)],
    )


def test_clean_pass():
    v = verdict(reasoning=f"Unemployment fell to 5% in 2024 (E1), see {URL}.")
    assert check_rationale(v, evidence()) == []


def test_fake_number():
    probs = check_rationale(verdict(reasoning="Unemployment fell to 7% in 2024."), evidence())
    assert len(probs) == 1 and "7" in probs[0]


def test_year_counts_as_number():
    probs = check_rationale(verdict(reasoning="This happened in 2019."), evidence())
    assert any("2019" in p for p in probs)


def test_number_formats():
    ok = [
        "5 percent", "5.0%", "1.2 million jobs", "1200000 jobs", "1,200,000 jobs",
        "2 million",
    ]
    for text in ok:
        assert check_rationale(verdict(reasoning=text), evidence()) == [], text


def test_evidence_ids_ignored():
    assert check_rationale(verdict(reasoning="E1 and F1 agree."), evidence()) == []


def test_fake_url():
    probs = check_rationale(verdict(reasoning="See https://evil.example/x."), evidence())
    assert len(probs) == 1 and "evil.example" in probs[0]


def test_known_url_with_trailing_punctuation_and_slash():
    assert check_rationale(verdict(reasoning=f"Source: ({URL}/)."), evidence()) == []


def test_url_digits_not_counted_as_numbers():
    assert check_rationale(verdict(reasoning=f"Read {URL}"), evidence()) == []


def test_missing_quote_guard():
    v = ClaimVerdict.model_construct(
        claim_id="c1", label=VerdictLabel.FALSE, confidence=0.5, answer="No.", reasoning="x", citations=[])
    assert any("no citation" in p for p in check_rationale(v, evidence()))


def test_unverifiable_needs_no_quote():
    v = ClaimVerdict(claim_id="c1", label=VerdictLabel.UNVERIFIABLE, confidence=0.1,
                     answer="I couldn't confirm this.", reasoning="Nothing found.")
    assert check_rationale(v, evidence()) == []


def test_validate_verdict_passes_on_real_quote():
    assert validate_verdict(verdict(), evidence(), 1).passed


def test_validate_verdict_fake_quote():
    r = validate_verdict(verdict(quote="unemployment hit 9%"), evidence(), 1)
    assert not r.passed and r.failed_citations[0].reason == CitationFailure.QUOTE_NOT_FOUND


def test_validate_verdict_unknown_id():
    r = validate_verdict(verdict(eid="E9"), evidence(), 1)
    assert r.failed_citations[0].reason == CitationFailure.UNKNOWN_EVIDENCE_ID


def test_validate_verdict_blank_quote():
    v = verdict().model_copy(update={"citations": [Citation.model_construct(evidence_id="E1", quote="  ", stance=Stance.SUPPORTS)]})
    r = validate_verdict(v, evidence(), 1)
    assert r.failed_citations[0].reason == CitationFailure.QUOTE_NOT_FOUND


# ------------------------------------------------------------ v2 confidence in consensus


def _v2_case():
    from app.schemas import Citation, ClaimVerdict, ComponentCheck, ComponentStatus, EvidenceItem, RankedEvidence, Stance, VerdictLabel
    ev = RankedEvidence(claim_id="c1", guardian=[
        EvidenceItem(id="E1", url="https://alpha.example/1", title="Alpha", passage="Alpha reported the event.", rerank_score=0.5, source_name="A"),
        EvidenceItem(id="E2", url="https://beta.example/2", title="Beta", passage="Beta covered something else.", rerank_score=0.5, source_name="B")])
    v = ClaimVerdict(claim_id="c1", label=VerdictLabel.TRUE, confidence=0.99, answer="a", reasoning="r",
                     citations=[Citation(evidence_id=i, quote="p", stance=Stance.SUPPORTS) for i in ("E1", "E2")],
                     components=[ComponentCheck(name="x", status=ComponentStatus.SUPPORTED, evidence_ids=["E1", "E2"])])
    return v, ev


def test_consensus_fills_named_factors_and_ignores_the_models_self_report():
    from app.rules import compute_consensus
    v, ev = _v2_case()
    factors = {}
    high = compute_consensus(v, ev, factors=factors)
    assert factors["evidence_strength"] == 1.0 and factors["source_independence"] == pytest.approx(2 / 3, abs=1e-3)
    v.confidence = 0.01
    assert compute_consensus(v, ev).final_confidence == high.final_confidence


def test_consensus_confidence_drops_with_fallback_retry_and_disagreement():
    from app.rules import compute_consensus
    v, ev = _v2_case()
    base = compute_consensus(v, ev).final_confidence
    weaker = compute_consensus(v, ev, fallback_used=True, quote_first_try=False, judge_agreement=0.0)
    assert weaker.final_confidence < base <= 0.70
