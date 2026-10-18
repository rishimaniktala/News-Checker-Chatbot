"""Shared Pydantic contracts for the news validator pipeline.

Flow:  NormalizedInput -> ClaimExtraction -> RankedEvidence -> ClaimVerdict (LLM)
       -> ValidationResult -> ConsensusResult -> ClaimReport -> FinalReport

Models marked [LLM OUTPUT] are what an LLM must return (structured output).
Everything else is built by plain code.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------- enums


class VerdictLabel(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    MISLEADING = "MISLEADING"
    UNVERIFIABLE = "UNVERIFIABLE"


class Stance(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


class InputType(str, Enum):
    URL = "url"
    TEXT = "text"
    IMAGE = "image"


class TimeSensitivity(str, Enum):
    EVERGREEN = "evergreen"  # true/false regardless of date
    RECENT = "recent"  # depends on recent events
    BREAKING = "breaking"  # unfolding now, evidence may be stale


class EvidenceOrigin(str, Enum):
    GUARDIAN = "guardian"
    FACTCHECK = "factcheck"


class CitationFailure(str, Enum):
    UNKNOWN_EVIDENCE_ID = "unknown_evidence_id"
    QUOTE_NOT_FOUND = "quote_not_found"
    LINK_DEAD = "link_dead"


class Step(str, Enum):
    NORMALIZE = "normalize"
    EXTRACT = "extract_claims"
    RETRIEVE = "retrieve"
    VERDICT = "verdict"
    VALIDATE = "validate"
    CONSENSUS = "consensus"
    DONE = "done"


class StepStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"


# ---------------------------------------------------- 1. input / extraction


class NormalizedInput(BaseModel):
    """Output of Normalize: everything downstream sees plain text."""

    input_type: InputType
    text: str = Field(description="Article body, pasted rumour, or OCR text.")
    source_url: Optional[str] = None
    context_note: Optional[str] = Field(
        default=None,
        description="Images only: short note on format, e.g. 'meme', 'screenshot of a tweet', 'satire site'.",
    )


class OcrResult(BaseModel):
    """[LLM OUTPUT] Image-to-text step (Gemini), feeds NormalizedInput."""

    text: str = Field(description="All readable text in the image, transcribed verbatim.")
    context_note: str = Field(
        description="One or two short sentences: format (meme, tweet screenshot, headline, ...) "
        "plus any visible attribution (account, outlet, date) and satire cues."
    )
    is_legible: bool = Field(description="False if there is no readable text.")

    def to_normalized_input(self) -> "NormalizedInput":
        return NormalizedInput(
            input_type=InputType.IMAGE, text=self.text, context_note=self.context_note
        )


class Claim(BaseModel):
    id: str = Field(description="Short id such as 'c1', 'c2', 'c3'.")
    text: str = Field(
        description="Self-contained, checkable statement. No pronouns or 'this'/'the article'."
    )
    checkworthy: bool = Field(
        description="False for opinions, predictions, satire, or anything not verifiable."
    )
    skip_reason: Optional[str] = Field(
        default=None, description="Required when checkworthy is false."
    )
    search_queries: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="2-3 distinct search queries for a news archive. Empty if not checkworthy.",
    )
    time_sensitivity: TimeSensitivity = TimeSensitivity.EVERGREEN

    @model_validator(mode="after")
    def _check_consistency(self):
        if self.checkworthy and not self.search_queries:
            raise ValueError("checkworthy claims need at least one search query")
        if not self.checkworthy and not self.skip_reason:
            raise ValueError("non-checkworthy claims need a skip_reason")
        return self


class ClaimExtraction(BaseModel):
    """[LLM OUTPUT] Extract claims step."""

    claims: list[Claim] = Field(max_length=3)
    notes: Optional[str] = Field(
        default=None, description="Anything odd about the input, e.g. 'content is satire'."
    )


# ------------------------------------------------------------- 2. evidence


class EvidenceItem(BaseModel):
    """A Guardian passage, after rerank."""

    id: str = Field(description="'E1', 'E2', ... unique within a claim.")
    source_name: str = "The Guardian"
    url: str
    title: str
    published_at: Optional[datetime] = None
    passage: str = Field(description="Text the verdict model may quote from, verbatim.")
    rerank_score: float = Field(ge=0.0, le=1.0)


class FactCheckReview(BaseModel):
    """One published fact-check from the Fact Check API."""

    id: str = Field(description="'F1', 'F2', ... unique within a claim.")
    publisher: str
    url: str
    claim_reviewed: str = Field(description="The claim the fact-checker actually reviewed.")
    raw_rating: str = Field(description="Publisher's own wording, e.g. 'Mostly False'.")
    normalized_label: Optional[VerdictLabel] = Field(
        default=None, description="None when the rating could not be mapped."
    )
    match_score: float = Field(
        ge=0.0, le=1.0, description="Embedding similarity between our claim and claim_reviewed."
    )
    reviewed_at: Optional[datetime] = None


class RankedEvidence(BaseModel):
    """Everything the Verdict step is allowed to cite for one claim."""

    claim_id: str
    guardian: list[EvidenceItem] = Field(default_factory=list)
    factchecks: list[FactCheckReview] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1, le=3)

    @property
    def valid_ids(self) -> set[str]:
        return {e.id for e in self.guardian} | {f.id for f in self.factchecks}

    @property
    def is_empty(self) -> bool:
        return not self.guardian and not self.factchecks


# -------------------------------------------------------------- 3. verdict


class Citation(BaseModel):
    evidence_id: str = Field(description="Id of an EvidenceItem or FactCheckReview given in the prompt.")
    quote: str = Field(
        min_length=1,
        description="Exact, verbatim substring of that item's text. Do not paraphrase.",
    )
    stance: Stance


class ClaimVerdict(BaseModel):
    """[LLM OUTPUT] Verdict step."""

    claim_id: str
    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    answer: str = Field(
        max_length=300,
        description="Direct plain-language reply to the claim, e.g. 'No, Anthropic has not shut down.' "
        "Starts with Yes / No / Partly / I couldn't confirm, and must agree with label.",
    )
    reasoning: str = Field(
        max_length=800,
        description="What is actually happening according to the sources, 2-4 sentences, with names, "
        "dates and numbers. For FALSE/MISLEADING, state the correct version explicitly.",
    )
    citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_unverifiable_needs_citations(self):
        if self.label != VerdictLabel.UNVERIFIABLE and not self.citations:
            raise ValueError("TRUE/FALSE/MISLEADING verdicts must cite at least one quote")
        return self


# ------------------------------------------- 4. validation / consensus (code)


class FailedCitation(BaseModel):
    evidence_id: str
    quote: str
    reason: CitationFailure


class ValidationResult(BaseModel):
    claim_id: str
    passed: bool
    failed_citations: list[FailedCitation] = Field(default_factory=list)
    attempt: int = Field(ge=1, le=3)

    @property
    def retry_hint(self) -> Optional[str]:
        """Text for the Verdict prompt's previous_failure slot."""
        if self.passed:
            return None
        lines = [f"- {f.evidence_id}: {f.reason.value} ({f.quote[:80]!r})" for f in self.failed_citations]
        return "Your previous answer had invalid citations:\n" + "\n".join(lines)


class ConsensusResult(BaseModel):
    claim_id: str
    final_label: VerdictLabel
    final_confidence: float = Field(ge=0.0, le=1.0)
    agreement_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Share of cited evidence whose stance matches final_label.",
    )
    single_source: bool = Field(description="Only Guardian OR only Fact Check had usable evidence.")
    factcheck_label: Optional[VerdictLabel] = Field(
        default=None, description="Best-matching Fact Check rating, if any."
    )
    conflict: bool = Field(
        default=False, description="LLM label disagrees with a high-match Fact Check rating."
    )
    label_changed: bool = Field(
        default=False,
        description="final_label differs from the LLM's label, so the LLM's answer text is stale.",
    )
    notes: Optional[str] = None


# ------------------------------------------------------------- 5. outputs


class ClaimReport(BaseModel):
    claim: Claim
    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    answer: str = Field(description="Direct reply to this claim; the main thing the user reads.")
    reasoning: str = Field(description="What is actually happening, per the sources.")
    citations: list[Citation] = Field(default_factory=list)
    evidence: Optional[RankedEvidence] = Field(
        default=None, description="Kept so the UI can link citations to URLs."
    )
    consensus: ConsensusResult
    attempts: int = Field(ge=1, le=3)


class FinalReport(BaseModel):
    run_id: str
    input: NormalizedInput
    overall_label: VerdictLabel
    overall_confidence: float = Field(ge=0.0, le=1.0)
    claims: list[ClaimReport] = Field(default_factory=list)
    skipped_claims: list[Claim] = Field(
        default_factory=list, description="Claims marked not checkworthy."
    )
    answer: str = Field(
        description="Combined plain-language reply to the whole input; per-claim answers joined by code."
    )
    disclaimer: str = (
        "Verdicts reflect what The Guardian and published fact-checks report, "
        "not independently established truth."
    )


class TraceEvent(BaseModel):
    """One SSE message for the live trace in the frontend."""

    run_id: str
    step: Step
    status: StepStatus
    claim_id: Optional[str] = None
    message: str = ""
    payload: Optional[dict] = None
    ts: datetime = Field(default_factory=datetime.utcnow)
