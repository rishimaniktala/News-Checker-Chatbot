"""Plain-code rules: citation validator, rating normalization, consensus, roll-up.

No LLM calls here. Everything is deterministic and unit-testable.
"""

import re
from datetime import date
import unicodedata
from decimal import Decimal
from typing import Callable, Optional

from .schemas import (
    Citation,
    CitationFailure,
    ClaimReport,
    ClaimVerdict,
    ConsensusResult,
    FailedCitation,
    RankedEvidence,
    Stance,
    ValidationResult,
    VerdictLabel,
)

MAX_ATTEMPTS = 3
FACTCHECK_MATCH_THRESHOLD = 0.75  # same threshold the Verdict prompt uses

# confidence caps
CAP_SINGLE_SOURCE = 0.70
CAP_CONFLICT = 0.60
CAP_UNVERIFIABLE = 0.40

# weights for final confidence (LLM self-report is only one input)
W_LLM, W_AGREEMENT, W_CORROBORATION = 0.5, 0.3, 0.2


# ------------------------------------------------------------ validator


def _norm(text: str) -> str:
    """Normalise so harmless differences don't fail a quote: unicode form,
    curly quotes/dashes, whitespace. Case and wording stay strict."""
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("‘", "'").replace("’", "'")
        .replace("“", '"').replace("”", '"')
        .replace("–", "-").replace("—", "-")
    )
    return re.sub(r"\s+", " ", text).strip()


def _quotable_texts(evidence: RankedEvidence) -> dict[str, tuple[str, list[str]]]:
    """evidence_id -> (url, texts a quote may come from).

    Guardian: the passage. Fact-check: claim_reviewed or raw_rating,
    matching what the Verdict prompt allows."""
    out: dict[str, tuple[str, list[str]]] = {}
    for e in evidence.guardian:
        out[e.id] = (e.url, [_norm(e.passage)])
    for f in evidence.factchecks:
        out[f.id] = (f.url, [_norm(f.claim_reviewed), _norm(f.raw_rating)])
    return out


def validate_verdict(
    verdict: ClaimVerdict,
    evidence: RankedEvidence,
    attempt: int,
    link_is_alive: Optional[Callable[[str], bool]] = None,
) -> ValidationResult:
    """Check every citation: id exists, quote is verbatim, link resolves.

    link_is_alive: injected by the caller (e.g. an HTTP HEAD check). If None,
    the link check is skipped. Each URL is checked at most once.
    """
    sources = _quotable_texts(evidence)
    failures: list[FailedCitation] = []
    link_cache: dict[str, bool] = {}

    for c in verdict.citations:
        if c.evidence_id not in sources:
            failures.append(_fail(c, CitationFailure.UNKNOWN_EVIDENCE_ID))
            continue
        url, texts = sources[c.evidence_id]
        quote = _norm(c.quote)
        if not quote or not any(quote in t for t in texts):
            failures.append(_fail(c, CitationFailure.QUOTE_NOT_FOUND))
            continue
        if link_is_alive is not None:
            if url not in link_cache:
                link_cache[url] = link_is_alive(url)
            if not link_cache[url]:
                failures.append(_fail(c, CitationFailure.LINK_DEAD))

    return ValidationResult(
        claim_id=verdict.claim_id,
        passed=not failures,
        failed_citations=failures,
        attempt=attempt,
    )


def _fail(c: Citation, reason: CitationFailure) -> FailedCitation:
    return FailedCitation(evidence_id=c.evidence_id, quote=c.quote, reason=reason)


_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_ID_RE = re.compile(r"\b[EF]\d+\b")
_NUM_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(thousand|million|billion|trillion)\b)?",
    re.IGNORECASE,
)
_SCALE = {"thousand": 10**3, "million": 10**6, "billion": 10**9, "trillion": 10**12}


def _urls(text: str) -> list[str]:
    return [u.rstrip(".,;:)]}!?") for u in _URL_RE.findall(text)]


def _numbers(text: str) -> set[Decimal]:
    """Numeric values in text. '5%' and '5 percent' both give 5; '1,200' gives
    1200; '2 million' gives 2000000. URLs and evidence ids like E1 are ignored."""
    text = _ID_RE.sub(" ", _URL_RE.sub(" ", _norm(text)))
    out = set()
    for digits, scale in _NUM_RE.findall(text):
        n = Decimal(digits.replace(",", ""))
        out.add((n * _SCALE.get(scale.lower(), 1)).normalize())
    return out


_INSTRUCTION_LIKE = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?)"
    r"|\b(say|answer|respond|output|return|label)\b[^.\n]{0,40}\b(true|false|supported|contradicted)\b"
    r"|\bsystem\s*:|\byou\s+(must|are\s+now)\b",
    re.IGNORECASE,
)


def check_rationale(verdict: ClaimVerdict, evidence: RankedEvidence, claim_text: str = "") -> list[str]:
    """Problems with the verdict's answer and reasoning text; empty list means fine.

    Flags numbers that appear in no evidence text and URLs that were not
    retrieved. Numbers from the claim itself, publication years and the
    current year are allowed, since a refutation has to name them.
    Words like 'five' are not checked."""
    problems: list[str] = []
    prose = f"{verdict.answer}\n{verdict.reasoning}"

    texts = []
    urls = set()
    for e in evidence.guardian:
        texts += [e.passage, e.title]
        urls.add(e.url.rstrip("/"))
    for f in evidence.factchecks:
        texts += [f.claim_reviewed, f.raw_rating]
        urls.add(f.url.rstrip("/"))
    dates = [e.published_at for e in evidence.guardian] + [f.reviewed_at for f in evidence.factchecks]
    texts += [f"{f.match_score:.2f}" for f in evidence.factchecks]
    texts += [claim_text, str(date.today().year)] + [str(d.year) for d in dates if d]
    known = set().union(*(_numbers(t) for t in texts))

    for n in sorted(_numbers(prose)):
        if n not in known:
            problems.append(f"number {n:f} does not appear in any evidence text")
    for u in dict.fromkeys(_urls(prose)):
        if u.rstrip("/") not in urls:
            problems.append(f"url {u} was not one of the retrieved sources")

    for c in verdict.citations:
        if _INSTRUCTION_LIKE.search(c.quote):
            problems.append(f"quote from {c.evidence_id} reads like an instruction, not evidence")

    if verdict.label != VerdictLabel.UNVERIFIABLE and not any(c.quote.strip() for c in verdict.citations):
        problems.append("non-UNVERIFIABLE verdict has no citation with a quote")
    return problems


def should_retry(validation: ValidationResult) -> bool:
    return not validation.passed and validation.attempt < MAX_ATTEMPTS


# --------------------------------------------------- rating normalization

# Ordered: first match wins, so specific phrases come before general ones.
_RATING_PATTERNS: list[tuple[str, VerdictLabel]] = [
    # unverifiable
    ("unproven", VerdictLabel.UNVERIFIABLE),
    ("unverified", VerdictLabel.UNVERIFIABLE),
    ("unsupported", VerdictLabel.UNVERIFIABLE),
    ("no evidence", VerdictLabel.UNVERIFIABLE),
    ("cannot be verified", VerdictLabel.UNVERIFIABLE),
    # negations before plain true/accurate
    ("untrue", VerdictLabel.FALSE),
    ("not true", VerdictLabel.FALSE),
    ("not accurate", VerdictLabel.FALSE),
    ("not correct", VerdictLabel.FALSE),
    ("inaccurate", VerdictLabel.FALSE),
    ("incorrect", VerdictLabel.FALSE),
    # mixed
    ("half true", VerdictLabel.MISLEADING),
    ("half-true", VerdictLabel.MISLEADING),
    ("partly", VerdictLabel.MISLEADING),
    ("partially", VerdictLabel.MISLEADING),
    ("mixture", VerdictLabel.MISLEADING),
    ("mixed", VerdictLabel.MISLEADING),
    ("misleading", VerdictLabel.MISLEADING),
    ("missing context", VerdictLabel.MISLEADING),
    ("needs context", VerdictLabel.MISLEADING),
    ("out of context", VerdictLabel.MISLEADING),
    ("exaggerat", VerdictLabel.MISLEADING),
    ("distort", VerdictLabel.MISLEADING),
    ("outdated", VerdictLabel.MISLEADING),
    # mostly X
    ("mostly false", VerdictLabel.FALSE),
    ("mostly true", VerdictLabel.TRUE),
    # false family
    ("pants on fire", VerdictLabel.FALSE),
    ("false", VerdictLabel.FALSE),
    ("fake", VerdictLabel.FALSE),
    ("hoax", VerdictLabel.FALSE),
    ("fabricated", VerdictLabel.FALSE),
    ("scam", VerdictLabel.FALSE),
    ("satire", VerdictLabel.FALSE),
    # true family
    ("true", VerdictLabel.TRUE),
    ("accurate", VerdictLabel.TRUE),
    ("correct", VerdictLabel.TRUE),
    ("legit", VerdictLabel.TRUE),
]


def normalize_rating(raw_rating: str) -> Optional[VerdictLabel]:
    """Map a publisher's free-text rating to our labels. None if unmapped.

    An LLM fallback for None results can be added later; until then an
    unmapped review is simply ignored by consensus."""
    text = _norm(raw_rating).lower()
    for needle, label in _RATING_PATTERNS:
        if needle in text:
            return label
    return None


def apply_rating_normalization(evidence: RankedEvidence) -> RankedEvidence:
    """Fill normalized_label on every fact-check review (call after retrieval)."""
    for f in evidence.factchecks:
        if f.normalized_label is None:
            f.normalized_label = normalize_rating(f.raw_rating)
    return evidence


# ------------------------------------------------------------ consensus

_EXPECTED_STANCE = {
    VerdictLabel.TRUE: Stance.SUPPORTS,
    VerdictLabel.FALSE: Stance.REFUTES,
}


def _agreement_ratio(label: VerdictLabel, citations: list[Citation]) -> float:
    """Share of cited evidence whose stance matches the final label.

    TRUE -> 'supports', FALSE -> 'refutes'. MISLEADING means mixed evidence:
    1.0 if both supports and refutes are cited, else 0.5.
    UNVERIFIABLE has no agreement to measure: 0.0.
    """
    if label == VerdictLabel.UNVERIFIABLE or not citations:
        return 0.0
    if label == VerdictLabel.MISLEADING:
        stances = {c.stance for c in citations}
        return 1.0 if {Stance.SUPPORTS, Stance.REFUTES} <= stances else 0.5
    expected = _EXPECTED_STANCE[label]
    return sum(c.stance == expected for c in citations) / len(citations)


def _best_factcheck_label(evidence: RankedEvidence) -> Optional[VerdictLabel]:
    """Rating of the closest-matching fact-check, if it is a usable verdict."""
    usable = [
        f for f in evidence.factchecks
        if f.normalized_label not in (None, VerdictLabel.UNVERIFIABLE)
        and f.match_score >= FACTCHECK_MATCH_THRESHOLD
    ]
    if not usable:
        return None
    return max(usable, key=lambda f: f.match_score).normalized_label


def unverifiable_result(claim_id: str, notes: str) -> ConsensusResult:
    """Used when validation fails MAX_ATTEMPTS times or no evidence exists."""
    return ConsensusResult(
        claim_id=claim_id,
        final_label=VerdictLabel.UNVERIFIABLE,
        final_confidence=0.0,
        agreement_ratio=0.0,
        single_source=False,
        notes=notes,
    )


def compute_consensus(verdict: ClaimVerdict, evidence: RankedEvidence) -> ConsensusResult:
    """Combine the validated LLM verdict with the best Fact Check rating.

    Call only with a verdict that passed validation. Rules:
      - fact-check agrees with LLM        -> keep label, corroborated
      - fact-check disagrees              -> conflict; follow the fact-check
      - LLM UNVERIFIABLE, fact-check has a rating -> adopt it (single source)
      - no usable fact-check              -> keep LLM label, single source
      - nothing usable at all             -> UNVERIFIABLE
    """
    fc_label = _best_factcheck_label(evidence)
    cited_ids = {c.evidence_id for c in verdict.citations}
    guardian_ids = {e.id for e in evidence.guardian}
    guardian_cited = bool(cited_ids & guardian_ids)

    label = verdict.label
    llm_label = verdict.label
    conflict = False
    notes: Optional[str] = None

    if label == VerdictLabel.UNVERIFIABLE and fc_label is None:
        res = unverifiable_result(verdict.claim_id, "No sufficient evidence from either source.")
        res.final_confidence = min(verdict.confidence, CAP_UNVERIFIABLE)
        return res

    if fc_label is not None and fc_label != label:
        if label == VerdictLabel.UNVERIFIABLE:
            notes = "Guardian evidence was insufficient; label taken from fact-check."
        else:
            conflict = True
            notes = f"LLM said {label.value} but a matching fact-check says {fc_label.value}; following the fact-check."
        label = fc_label

    agreement = _agreement_ratio(label, verdict.citations)
    corroborated = fc_label == label and guardian_cited
    single_source = not corroborated

    if conflict:
        corroboration = 0.0
    elif corroborated:
        corroboration = 1.0
    else:
        corroboration = 0.5

    confidence = (
        W_LLM * verdict.confidence + W_AGREEMENT * agreement + W_CORROBORATION * corroboration
    )
    if single_source:
        confidence = min(confidence, CAP_SINGLE_SOURCE)
    if conflict:
        confidence = min(confidence, CAP_CONFLICT)

    return ConsensusResult(
        claim_id=verdict.claim_id,
        final_label=label,
        final_confidence=round(confidence, 3),
        agreement_ratio=round(agreement, 3),
        single_source=single_source,
        factcheck_label=fc_label,
        conflict=conflict,
        label_changed=label != llm_label,
        notes=notes,
    )


def factcheck_answer(evidence: RankedEvidence) -> Optional[str]:
    """Replacement answer text when consensus overrode the LLM's label
    (ConsensusResult.label_changed). Built from the best matching fact-check."""
    usable = [f for f in evidence.factchecks if f.match_score >= FACTCHECK_MATCH_THRESHOLD]
    if not usable:
        return None
    f = max(usable, key=lambda x: x.match_score)
    return f'{f.publisher} rated a matching claim "{f.raw_rating}": {f.claim_reviewed}.'


# -------------------------------------------------------------- roll-up


def rollup_overall(reports: list[ClaimReport]) -> tuple[VerdictLabel, float]:
    """One label for the whole input, from per-claim reports.

    UNVERIFIABLE claims are ignored for the label (but lower the confidence).
    All same label -> that label; any mix (incl. TRUE+FALSE) -> MISLEADING.
    No claims or all UNVERIFIABLE -> UNVERIFIABLE.
    """
    if not reports:
        return VerdictLabel.UNVERIFIABLE, 0.0

    verified = [r for r in reports if r.label != VerdictLabel.UNVERIFIABLE]
    if not verified:
        return VerdictLabel.UNVERIFIABLE, min(r.confidence for r in reports)

    labels = {r.label for r in verified}
    overall = labels.pop() if len(labels) == 1 else VerdictLabel.MISLEADING
    coverage = len(verified) / len(reports)
    confidence = min(r.confidence for r in verified) * coverage
    return overall, round(confidence, 3)
