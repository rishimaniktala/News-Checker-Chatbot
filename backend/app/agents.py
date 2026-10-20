"""LLM agents: the only file that calls Gemini.

Formats come from schemas.py and prompts from prompts.py; this file sends them
to Gemini and returns checked Pydantic objects. The evidence-check step has no
format or prompt in those files yet, so its EvidenceCheck model and prompt live
here (move them over later if the team agrees).

    run_ocr()         image bytes                      -> OcrResult
    extract_claims()  NormalizedInput                  -> ClaimExtraction
    check_evidence()  Claim + RankedEvidence + queries -> EvidenceCheck   (sufficient? or new queries)
    give_verdict()    Claim + RankedEvidence           -> ClaimVerdict

The orchestrator decides the order, the retrieval loop and the validator retries.

Setup:
    pip install -U google-genai pydantic
    $env:GEMINI_API_KEY="..."          (PowerShell)  /  export GEMINI_API_KEY=...  (macOS/Linux)
    optional: MODEL_PRIMARY, MODEL_FALLBACK, PROMPT_VERSION
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from google.genai import types
from pydantic import BaseModel, Field

from .llm import AgentError, embed, generate as _call, set_usage_sink  # noqa: F401  (re-exported)
from .prompts import (
    _outlet,
    neutralize as _neutralize,
    EXTRACTION_SYSTEM_PROMPT,
    OCR_SYSTEM_PROMPT,
    OCR_USER_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    VERDICT_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
    build_review_user_prompt,
    build_extraction_user_prompt,
    build_verdict_user_prompt,
)
from .schemas import (
    Claim,
    ClaimExtraction,
    ClaimVerdict,
    NormalizedInput,
    OcrResult,
    RankedEvidence,
    VerdictLabel,
)

# ------------------------------------------------- evidence check: format
# Not in schemas.py / prompts.py yet; kept here so those files stay unchanged.


class EvidenceDecision(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"


class EvidenceCheck(BaseModel):
    """[LLM OUTPUT] Is the retrieved evidence good enough for a verdict?

    Sits between Retrieve and Verdict. If INSUFFICIENT, new_search_queries
    go back to Retrieve (max 3 retrieval rounds per claim)."""

    claim_id: str
    decision: EvidenceDecision
    relevant_ids: list[str] = Field(
        default_factory=list,
        description="Evidence ids (E1, F2, ...) that are actually about this claim's people, event and time.",
    )
    covered_components: list[str] = Field(
        default_factory=list, description="Parts of the claim (who, what, when, ...) the evidence addresses for the right period."
    )
    missing_components: list[str] = Field(
        default_factory=list, description="Parts of the claim no item addresses yet."
    )
    reason: str = Field(max_length=300, description="One sentence explaining the decision.")
    new_search_queries: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Only if insufficient: 1-3 NEW keyword queries (3-6 words each), different from those already tried.",
    )


# The evidence-check prompt text lives in prompt_files/<version>/evidence_check.md.


def build_verify_user_prompt(
    claim: Claim,
    evidence: RankedEvidence,
    tried_queries: list[str],
    today: date | None = None,
) -> str:
    """User message for the evidence-check call, laid out like the verdict prompt."""
    today = today or date.today()
    parts = [
        f"Today's date: {today.isoformat()}",
        f'<claim id="{claim.id}" time_sensitivity="{claim.time_sensitivity.value}">',
        _neutralize(claim.text),
        "</claim>",
        "",
        "Queries already tried:",
        *[f"- {q}" for q in tried_queries],
        "",
        "<evidence>",
    ]
    if evidence.is_empty:
        parts.append("(no evidence was found)")
    for e in evidence.guardian:
        published = e.published_at.date().isoformat() if e.published_at else "unknown"
        parts += [
            f"[{e.id}] {_outlet(e.source_name)} | published: {published} | title: {_neutralize(e.title)}",
            f"passage: {_neutralize(e.passage)}",
            "",
        ]
    for f in evidence.factchecks:
        parts += [
            f"[{f.id}] Fact-check by {_neutralize(f.publisher)} | match_score: {f.match_score:.2f}",
            f"claim reviewed: {_neutralize(f.claim_reviewed)}",
            "",
        ]
    parts += ["</evidence>", "", f'Return the evidence check for claim_id "{claim.id}".']
    return "\n".join(parts)

# --------------------------------------------------------------- the agents


def run_ocr(image_bytes: bytes, mime_type: str = "image/png") -> OcrResult:
    """Read the text out of an uploaded image (screenshot, meme, headline photo).
    Use result.to_normalized_input() to feed extract_claims()."""
    contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), OCR_USER_PROMPT]
    return _call(OCR_SYSTEM_PROMPT, contents, OcrResult, role="ocr")


def extract_claims(inp: NormalizedInput, today: date | None = None) -> ClaimExtraction:
    """LLM call 1: up to 3 claims, each with search queries if checkworthy."""
    for attempt in range(2):
        result = _call(EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt(inp, today), ClaimExtraction,
                       role="extract")
        # Gemini Flash sometimes emits newlines in place of an accented letter; ask again once.
        if not any("\n" in c.text for c in result.claims):
            break
    for c in result.claims:
        c.text = " ".join(c.text.split())
    # Make claim ids unique even if the model repeats one (orchestrator keys on them).
    seen: set[str] = set()
    for i, c in enumerate(result.claims, start=1):
        if not c.id or c.id in seen:
            c.id = f"c{i}"
        seen.add(c.id)
    return result


def check_evidence(
    claim: Claim,
    evidence: RankedEvidence,
    tried_queries: list[str],
    today: date | None = None,
) -> EvidenceCheck:
    """LLM call 2: is this evidence about the claim? If not, propose new queries."""
    user = build_verify_user_prompt(claim, evidence, tried_queries, today)
    check = _call(VERIFY_SYSTEM_PROMPT, user, EvidenceCheck, role="evidence")

    # Plain-code safety checks.
    check.claim_id = claim.id
    check.relevant_ids = [i for i in check.relevant_ids if i in evidence.valid_ids]
    if check.decision == EvidenceDecision.SUFFICIENT and not check.relevant_ids:
        check.decision = EvidenceDecision.INSUFFICIENT
    tried = {q.strip().lower() for q in tried_queries}
    check.new_search_queries = [q for q in check.new_search_queries if q.strip().lower() not in tried]
    if check.decision == EvidenceDecision.SUFFICIENT:
        check.new_search_queries = []
    return check


def give_verdict(
    claim: Claim,
    evidence: RankedEvidence,
    previous_failure: str | None = None,
    today: date | None = None,
) -> ClaimVerdict:
    """LLM call 3: label + answer + reasoning + exact-quote citations.

    previous_failure: ValidationResult.retry_hint from rules.validate_verdict,
    when the last attempt had invalid citations.
    """
    user = build_verdict_user_prompt(claim, evidence, today, previous_failure)
    verdict = _call(VERDICT_SYSTEM_PROMPT, user, ClaimVerdict, role="judge")
    verdict.claim_id = claim.id  # trust our id, not the model's copy of it
    return verdict


def give_review(
    claim: Claim,
    evidence: RankedEvidence,
    first: ClaimVerdict,
    derived_label: VerdictLabel,
    today: date | None = None,
) -> ClaimVerdict:
    """Second opinion when the judge's label and its components disagree."""
    user = build_review_user_prompt(claim, evidence, first, derived_label.value, today)
    verdict = _call(REVIEW_SYSTEM_PROMPT, user, ClaimVerdict, role="review")
    verdict.claim_id = claim.id
    return verdict
