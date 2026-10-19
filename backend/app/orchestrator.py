"""Example orchestrator: runs the whole pipeline for one input, using
agents.py (LLM calls) and rules.py (validator, consensus, roll-up).

Per checkworthy claim (loop caps come from settings.max_iterations):
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

import logging
from functools import partial
from typing import Callable

from .agents import EvidenceDecision, check_evidence, extract_claims, give_verdict
from .budget import RunBudget
from .config import Settings, log_failure, redact
from .rules import (
    MAX_ATTEMPTS,
    apply_rating_normalization,
    check_rationale,
    compute_consensus,
    factcheck_answer,
    rollup_overall,
    unverifiable_result,
    validate_verdict,
)
from .schemas import (
    Claim,
    ClaimReport,
    FinalReport,
    NormalizedInput,
    RankedEvidence,
    Step,
    StepStatus,
    TraceEvent,
    VerdictLabel,
)

log = logging.getLogger(__name__)

MAX_SEARCH_ROUNDS = 3
SearchFn = Callable[[Claim, list[str], int], RankedEvidence]
Emit = Callable[[dict], None]


def trace(emit: Emit, run_id: str, step: Step, status: StepStatus,
          claim_id: str | None = None, message: str = "", payload: dict | None = None) -> None:
    event = TraceEvent(run_id=run_id, step=step, status=status, claim_id=claim_id,
                       message=message, payload=payload)
    emit({"type": "trace", **event.model_dump(mode="json")})


def _unverifiable_report(claim: Claim, why: str, evidence: RankedEvidence | None,
                         answer: str = "I couldn't confirm this: no relevant coverage was found.") -> ClaimReport:
    return ClaimReport(
        claim=claim,
        label=VerdictLabel.UNVERIFIABLE,
        confidence=0.0,
        answer=answer,
        reasoning=why,
        evidence=evidence,
        consensus=unverifiable_result(claim.id, why),
        attempts=1,
    )


def check_claim(claim: Claim, search_fn: SearchFn, settings: Settings, budget: RunBudget,
                emit: Emit, run_id: str, source_url: str | None = None) -> ClaimReport:
    t = partial(trace, emit, run_id, claim_id=claim.id)
    rounds = min(MAX_SEARCH_ROUNDS, settings.max_iterations)
    queries = list(claim.search_queries)
    tried: list[str] = []
    evidence: RankedEvidence | None = None
    sufficient = False
    reported: set[str] = set()

    for round_no in range(1, rounds + 1):
        if budget.exhausted:
            t(Step.RETRIEVE, StepStatus.FAILED, message="Cost cap reached; stopping the search.")
            break
        queries = [q for q in queries if budget.register_query(q)]
        if not queries:
            t(Step.RETRIEVE, StepStatus.COMPLETED, message="No new queries to try; stopping the search.")
            break
        tried += queries
        t(Step.RETRIEVE, StepStatus.STARTED, payload={"round": round_no, "queries": queries})
        evidence = search_fn(claim, queries, round_no)
        for note in getattr(search_fn, "unavailable", []):
            if note not in reported:
                reported.add(note)
                t(Step.RETRIEVE, StepStatus.COMPLETED, message=f"Source problem: {note}.")
        evidence.guardian = [e for e in evidence.guardian if e.url != source_url]
        apply_rating_normalization(evidence)
        t(Step.RETRIEVE, StepStatus.COMPLETED, message=(
            f"{len(evidence.guardian)} articles, {len(evidence.factchecks)} fact-checks"))

        check = check_evidence(claim, evidence, tried)
        sufficient = check.decision == EvidenceDecision.SUFFICIENT
        will_retry = not sufficient and bool(check.new_search_queries) and round_no < rounds
        t(Step.RETRIEVE, StepStatus.RETRY if will_retry else StepStatus.COMPLETED,
          message=check.reason, payload={"round": round_no, "decision": check.decision.value})
        if not will_retry:
            break
        queries = check.new_search_queries

    if not sufficient:
        why = f"No relevant coverage found after {len(tried)} search queries."
        t(Step.RETRIEVE, StepStatus.FAILED, message=why)
        return _unverifiable_report(claim, why, evidence)

    attempts = min(MAX_ATTEMPTS, settings.max_iterations)
    failure: str | None = None
    verdict = None
    attempt = 0
    for attempt in range(1, attempts + 1):
        if budget.exhausted:
            t(Step.VERDICT, StepStatus.FAILED, message="Cost cap reached; stopping.")
            break
        t(Step.VERDICT, StepStatus.STARTED, payload={"attempt": attempt})
        candidate = give_verdict(claim, evidence, previous_failure=failure)
        t(Step.VERDICT, StepStatus.COMPLETED, payload={"attempt": attempt, "label": candidate.label.value})
        if not settings.enable_validator:
            t(Step.VALIDATE, StepStatus.COMPLETED, message="Validator disabled; verdict accepted unchecked.")
            verdict = candidate
            break
        validation = validate_verdict(candidate, evidence, attempt)
        issues = check_rationale(candidate, evidence) if validation.passed else []
        passed = validation.passed and not issues
        if not passed:
            failure = validation.retry_hint or "Problems with your answer text:\n" + "\n".join(issues)
        status = (StepStatus.COMPLETED if passed
                  else StepStatus.RETRY if attempt < attempts else StepStatus.FAILED)
        t(Step.VALIDATE, status, payload={"attempt": attempt, "passed": passed},
          message="" if passed else failure)
        if passed:
            verdict = candidate
            break

    if verdict is None:
        return _unverifiable_report(
            claim, "The model's citations could not be verified against the sources.", evidence)

    consensus = compute_consensus(verdict, evidence)
    t(Step.CONSENSUS, StepStatus.COMPLETED, message=f"{consensus.final_label.value}")
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


def check_input(inp: NormalizedInput, search_fn: SearchFn, settings: Settings, budget: RunBudget,
                emit: Emit, run_id: str) -> FinalReport:
    t = partial(trace, emit, run_id)
    t(Step.EXTRACT, StepStatus.STARTED)
    extraction = extract_claims(inp)
    checkable = [c for c in extraction.claims if c.checkworthy]
    skipped = [c for c in extraction.claims if not c.checkworthy]
    t(Step.EXTRACT, StepStatus.COMPLETED,
      message=f"{len(checkable)} claims to check, {len(skipped)} skipped")

    reports = []
    for claim in checkable:
        try:
            reports.append(check_claim(claim, search_fn, settings, budget, emit, run_id, inp.source_url))
        except Exception as e:
            log_failure(log, f"claim {claim.id} failed")
            t(Step.VERDICT, StepStatus.FAILED, claim.id, redact(f"{type(e).__name__}: {e}")[:300])
            reports.append(_unverifiable_report(
                claim, "A step failed while checking this claim.", None,
                answer="I couldn't check this claim because something went wrong on my side."))
    overall, confidence = rollup_overall(reports)
    answer = " ".join(r.answer for r in reports) or (
        extraction.notes or "Nothing in this input could be fact-checked.")
    return FinalReport(
        run_id=run_id,
        input=inp,
        overall_label=overall,
        overall_confidence=confidence,
        claims=reports,
        skipped_claims=skipped,
        answer=answer,
    )
