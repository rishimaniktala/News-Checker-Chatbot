import pytest

from app.judge import derive_label, more_conservative, reconcile
from app.schemas import (
    Citation, ClaimVerdict, ComponentCheck, ComponentStatus as S, EvidenceItem, RankedEvidence, Stance, VerdictLabel as L,
)


def comp(status, ids=("E1",), name="part"):
    return ComponentCheck(name=name, status=status, evidence_ids=list(ids))


@pytest.mark.parametrize("parts, expected", [
    ([], L.UNVERIFIABLE),
    ([comp(S.SUPPORTED)], L.TRUE),
    ([comp(S.SUPPORTED), comp(S.SUPPORTED)], L.TRUE),
    ([comp(S.SUPPORTED), comp(S.UNKNOWN, ())], L.UNVERIFIABLE),
    ([comp(S.UNKNOWN, ())], L.UNVERIFIABLE),
    ([comp(S.CONTRADICTED)], L.FALSE),
    ([comp(S.CONTRADICTED), comp(S.UNKNOWN, ())], L.FALSE),
    ([comp(S.CONTRADICTED, ()), comp(S.UNKNOWN, ())], L.UNVERIFIABLE),
    ([comp(S.SUPPORTED), comp(S.CONTRADICTED)], L.MISLEADING),
    ([comp(S.SUPPORTED), comp(S.CONTRADICTED, ()), comp(S.UNKNOWN, ())], L.UNVERIFIABLE),
])
def test_derive_label_table(parts, expected):
    assert derive_label(parts) == expected


@pytest.mark.parametrize("a, b, expected", [
    (L.TRUE, L.TRUE, L.TRUE),
    (L.TRUE, L.UNVERIFIABLE, L.UNVERIFIABLE),
    (L.FALSE, L.MISLEADING, L.MISLEADING),
    (L.TRUE, L.MISLEADING, L.MISLEADING),
    (L.TRUE, L.FALSE, L.UNVERIFIABLE),
])
def test_more_conservative(a, b, expected):
    assert more_conservative(a, b) == expected
    assert more_conservative(b, a) == expected


def evidence():
    return RankedEvidence(claim_id="c1", guardian=[
        EvidenceItem(id="E1", url="https://x.test/a", title="t", passage="p", rerank_score=0.5)])


def verdict(label, components, cited=("E1",)):
    cites = [Citation(evidence_id=i, quote="p", stance=Stance.SUPPORTS) for i in cited]
    return ClaimVerdict(claim_id="c1", label=label, confidence=0.8, answer="a", reasoning="r",
                        citations=cites, components=components)


def test_reconcile_clean_verdict_has_no_problems():
    assert reconcile(verdict(L.TRUE, [comp(S.SUPPORTED)]), evidence()) == []


def test_reconcile_flags_unknown_component_id():
    problems = reconcile(verdict(L.TRUE, [comp(S.SUPPORTED, ("E9",))]), evidence())
    assert any("unknown ids: E9" in p for p in problems)


def test_reconcile_flags_component_id_without_citation():
    ev = evidence()
    ev.guardian.append(EvidenceItem(id="E2", url="https://x.test/b", title="t", passage="p", rerank_score=0.5))
    problems = reconcile(verdict(L.TRUE, [comp(S.SUPPORTED, ("E2",))]), ev)
    assert any("E2" in p and "no citation" in p for p in problems)


def test_reconcile_flags_settled_component_without_id():
    assert any("names no evidence id" in p for p in reconcile(verdict(L.MISLEADING, [comp(S.SUPPORTED, ()), comp(S.CONTRADICTED)]), evidence()))


@pytest.mark.parametrize("label", [L.TRUE, L.FALSE])
def test_reconcile_flags_true_or_false_without_components(label):
    assert reconcile(verdict(label, []), evidence())


def test_reconcile_allows_unverifiable_without_components():
    assert reconcile(ClaimVerdict(claim_id="c1", label=L.UNVERIFIABLE, confidence=0.1, answer="a", reasoning="r"), evidence()) == []
