"""Example orchestrator: runs the whole pipeline for one input, using
agents.py (LLM calls) and rules.py (validator, consensus, roll-up).

Per checkworthy claim:
    retrieve -> check_evidence ──insufficient──> new queries -> retrieve   (max 3 rounds)
                     │ sufficient
                     v
                give_verdict -> validate_verdict ──bad quotes──> give_verdict + retry_hint  (max 3)
                                     │ passed
                                     v
                              compute_consensus -> ClaimReport
Then rollup_overall -> FinalReport.

`search_fn` is the retrieval step (Guardian + Fact Check API + rerank), owned by
whoever builds retrieval: search_fn(claim, queries, attempt) -> RankedEvidence.
"""

from __future__ import annotations

import uuid
from typing import Callable

from .agents import EvidenceDecision, check_evidence, extract_claims, give_verdict
from .rules import (
    MAX_ATTEMPTS,
    apply_rating_normalization,
    compute_consensus,
    factcheck_answer,
    rollup_overall,
    should_retry,
    unverifiable_result,
    validate_verdict,
)
from .schemas import (
    Claim,
    ClaimReport,
    FinalReport,
    NormalizedInput,
    RankedEvidence,
    VerdictLabel,
)

MAX_SEARCH_ROUNDS = 3
SearchFn = Callable[[Claim, list[str], int], RankedEvidence]


def _unverifiable_report(claim: Claim, why: str, evidence: RankedEvidence | None) -> ClaimReport:
    return ClaimReport(
        claim=claim,
        label=VerdictLabel.UNVERIFIABLE,
        confidence=0.0,
        answer="I couldn't confirm this: no relevant coverage was found.",
        reasoning=why,
        evidence=evidence,
        consensus=unverifiable_result(claim.id, why),
        attempts=1,
    )


def check_claim(claim: Claim, search_fn: SearchFn, source_url: str | None = None,
                trace: list | None = None) -> ClaimReport:
    trace = trace if trace is not None else []
    queries = list(claim.search_queries)
    tried: list[str] = []
    evidence: RankedEvidence | None = None
    sufficient = False

    # 1. Retrieve <-> check_evidence loop
    for round_no in range(1, MAX_SEARCH_ROUNDS + 1):
        tried += queries
        evidence = search_fn(claim, queries, round_no)
        # The pasted article can't be evidence for itself.
        evidence.guardian = [e for e in evidence.guardian if e.url != source_url]
        apply_rating_normalization(evidence)

        check = check_evidence(claim, evidence, tried)
        trace.append({"claim": claim.id, "step": "verify_evidence", "round": round_no,
                      "queries": queries, "decision": check.decision.value, "reason": check.reason})
        if check.decision == EvidenceDecision.SUFFICIENT:
            sufficient = True
            break
        if not check.new_search_queries:
            break  # nothing new to try
        queries = check.new_search_queries

    if not sufficient:
        return _unverifiable_report(
            claim, f"No relevant coverage found after {len(tried)} search queries.", evidence)

    # 2. Verdict <-> validator loop
    failure: str | None = None
    verdict = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        candidate = give_verdict(claim, evidence, previous_failure=failure)
        validation = validate_verdict(candidate, evidence, attempt)
        trace.append({"claim": claim.id, "step": "validate", "attempt": attempt,
                      "label": candidate.label.value, "passed": validation.passed})
        if validation.passed:
            verdict = candidate
            break
        failure = validation.retry_hint
        if not should_retry(validation):
            break

    if verdict is None:
        return _unverifiable_report(
            claim, "The model's citations could not be verified against the sources.", evidence)

    # 3. Consensus
    consensus = compute_consensus(verdict, evidence)
    answer = verdict.answer
    if consensus.label_changed:
        answer = factcheck_answer(evidence) or answer
    return ClaimReport(
        claim=claim,
        label=consensus.final_label,
        confidence=consensus.final_confidence,
        answer=answer,
        reasoning=verdict.reasoning,
        citations=verdict.citations,
        evidence=evidence,
        consensus=consensus,
        attempts=attempt,
    )


def check_input(inp: NormalizedInput, search_fn: SearchFn, trace: list | None = None) -> FinalReport:
    extraction = extract_claims(inp)
    checkable = [c for c in extraction.claims if c.checkworthy]
    skipped = [c for c in extraction.claims if not c.checkworthy]

    reports = [check_claim(c, search_fn, inp.source_url, trace) for c in checkable]
    overall, confidence = rollup_overall(reports)
    answer = " ".join(r.answer for r in reports) or (
        extraction.notes or "Nothing in this input could be fact-checked.")
    return FinalReport(
        run_id=uuid.uuid4().hex[:12],
        input=inp,
        overall_label=overall,
        overall_confidence=confidence,
        claims=reports,
        skipped_claims=skipped,
        answer=answer,
    )


if __name__ == "__main__":
    # Demo with a fake search function. Needs GEMINI_API_KEY.
    # Set OFF_TOPIC = True to watch the query-rewriting loop instead.
    from .schemas import EvidenceItem, InputType

    OFF_TOPIC = False

    def fake_search(claim: Claim, queries: list[str], attempt: int) -> RankedEvidence:
        passage = ("Volvo reported higher car sales in Gothenburg this quarter." if OFF_TOPIC else
                   "Sweden has not banned cash. Shops may refuse cash payments, "
                   "but pharmacies and some essential services are required to accept it.")
        return RankedEvidence(
            claim_id=claim.id,
            attempt=attempt,
            guardian=[EvidenceItem(id="E1", url="https://www.theguardian.com/example",
                                   title="Sweden's cashless shift", passage=passage,
                                   rerank_score=0.8)],
        )

    inp = NormalizedInput(
        input_type=InputType.TEXT,
        text="Sverige förbjöd kontantbetalningar i alla butiker år 2025, enligt regeringen.",
    )
    trace: list = []
    report = check_input(inp, fake_search, trace)

    import json
    print(json.dumps(trace, indent=2, ensure_ascii=False))
    print(report.model_dump_json(indent=2, exclude={"claims": {"__all__": {"evidence"}}}))
