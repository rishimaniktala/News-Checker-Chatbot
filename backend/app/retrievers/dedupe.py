"""Count independent outlets behind a set of evidence. Interface fixed; backend-data improves the body."""

from ..schemas import RankedEvidence


def count_independent(evidence: RankedEvidence, evidence_ids: set[str] | None = None) -> int:
    """Distinct outlets among the given evidence ids (all items if None), syndicated copies collapsed."""
    names = {e.source_name for e in evidence.guardian if evidence_ids is None or e.id in evidence_ids}
    names |= {f.publisher for f in evidence.factchecks if evidence_ids is None or f.id in evidence_ids}
    return len(names)
