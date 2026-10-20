"""Pure-code checks on the judge's output: the label its components imply, and whether its ids hold up."""

from .schemas import ClaimVerdict, ComponentCheck, ComponentStatus, RankedEvidence, Stance, VerdictLabel

_COMMITTAL = {VerdictLabel.TRUE: 2, VerdictLabel.FALSE: 2, VerdictLabel.MISLEADING: 1, VerdictLabel.UNVERIFIABLE: 0}


def derive_label(components: list[ComponentCheck]) -> VerdictLabel:
    """TRUE if every part is supported; MISLEADING if some are supported and some contradicted;
    FALSE if a part is contradicted by cited evidence and none is supported; else UNVERIFIABLE."""
    if not components:
        return VerdictLabel.UNVERIFIABLE
    supported = any(c.status == ComponentStatus.SUPPORTED for c in components)
    contradicted = any(c.status == ComponentStatus.CONTRADICTED and c.evidence_ids for c in components)
    if supported and contradicted:
        return VerdictLabel.MISLEADING
    if contradicted:
        return VerdictLabel.FALSE
    if all(c.status == ComponentStatus.SUPPORTED for c in components):
        return VerdictLabel.TRUE
    return VerdictLabel.UNVERIFIABLE


def more_conservative(a: VerdictLabel, b: VerdictLabel) -> VerdictLabel:
    """The less committal label. TRUE against FALSE has no middle, so it becomes UNVERIFIABLE."""
    if a == b:
        return a
    if _COMMITTAL[a] == _COMMITTAL[b]:
        return VerdictLabel.UNVERIFIABLE
    return min(a, b, key=_COMMITTAL.get)


def reconcile(verdict: ClaimVerdict, evidence: RankedEvidence) -> list[str]:
    """Problems that make the components and citations disagree. Empty list means consistent."""
    problems: list[str] = []
    valid = evidence.valid_ids
    cited = {c.evidence_id for c in verdict.citations}
    settled = [c for c in verdict.components if c.status != ComponentStatus.UNKNOWN]
    for c in verdict.components:
        bad = [i for i in c.evidence_ids if i not in valid]
        if bad:
            problems.append(f'component "{c.name}" cites unknown ids: {", ".join(bad)}')
    for c in settled:
        if not c.evidence_ids:
            problems.append(f'component "{c.name}" is {c.status.value} but names no evidence id')
        known = [i for i in c.evidence_ids if i in valid]
        if known and not set(known) & cited:
            problems.append(f'component "{c.name}" relies on {", ".join(known)}, which has no citation')
    if verdict.label in (VerdictLabel.TRUE, VerdictLabel.FALSE) and not settled:
        problems.append(f"label {verdict.label.value} has no supported or contradicted component behind it")
    wanted = {VerdictLabel.TRUE: Stance.SUPPORTS, VerdictLabel.FALSE: Stance.REFUTES}.get(verdict.label)
    if wanted and verdict.citations and not any(c.stance == wanted for c in verdict.citations):
        problems.append(f"label {verdict.label.value} has no citation that {wanted.value} the claim")
    return problems
