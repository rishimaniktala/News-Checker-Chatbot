"""Prompts for the news validator. Output schemas live in schemas.py.

System prompts are files in prompt_files/<version>/. PROMPT_VERSION (env, default v2) picks the set.
"""

import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from .schemas import Claim, ClaimVerdict, NormalizedInput, RankedEvidence

PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v2").strip() or "v2"
PROMPT_DIR = Path(__file__).resolve().parent / "prompt_files"


def load_prompt(name: str, version: str | None = None) -> str:
    """Text of prompt_files/<version>/<name>.md; unknown versions fail at import, not mid-run."""
    version = version or PROMPT_VERSION
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", version):
        raise ValueError(f"bad prompt version {version!r}")
    if not re.fullmatch(r"[a-z_]+", name):
        raise ValueError(f"bad prompt name {name!r}")
    return (PROMPT_DIR / version / f"{name}.md").read_text(encoding="utf-8")


EXTRACTION_SYSTEM_PROMPT = load_prompt("extraction")
OCR_SYSTEM_PROMPT = load_prompt("ocr")
VERDICT_SYSTEM_PROMPT = load_prompt("verdict")
VERIFY_SYSTEM_PROMPT = load_prompt("evidence_check")
REVIEW_SYSTEM_PROMPT = load_prompt("review")

MAX_INPUT_CHARS = 8000
OCR_USER_PROMPT = "Read this image."


def build_extraction_user_prompt(inp: NormalizedInput, today: date | None = None) -> str:
    today = today or date.today()
    text = inp.text
    truncated = len(text) > MAX_INPUT_CHARS
    if truncated:
        text = text[:MAX_INPUT_CHARS]
    text = neutralize(text)

    parts = [
        f"Today's date: {today.isoformat()}",
        f"Input type: {inp.input_type.value}",
    ]
    if inp.source_url:
        parts.append(f"Source URL: {inp.source_url}")
    parts += ["", "<input>", text, "</input>"]
    if inp.context_note:
        parts += ["", "<context_note>", neutralize(inp.context_note), "</context_note>"]
    if truncated:
        parts.append("(Input was truncated for length.)")
    parts += ["", "Extract the claims."]
    return "\n".join(parts)


# --------------------------------------------------------------- VERDICT


_CLOSER = re.compile(r"<\s*/\s*(evidence|claim|input|context_note|first_verdict)\s*>", re.IGNORECASE)


def neutralize(text: str) -> str:
    """Stop untrusted text from closing our delimiter tags, whatever the case, spacing or width."""
    return _CLOSER.sub(lambda m: f"[/{m.group(1).lower()}]", unicodedata.normalize("NFKC", text))


_neutralize = neutralize


def _safe_id(claim_id: str) -> str:
    """Claim ids come from model output and sit inside a tag attribute, so keep only safe characters."""
    return re.sub(r"[^A-Za-z0-9_-]", "", claim_id)[:16] or "c1"


def _outlet(name: str) -> str:
    return "Guardian" if name == "The Guardian" else _neutralize(name)


def build_verdict_user_prompt(
    claim: Claim,
    evidence: RankedEvidence,
    today: date | None = None,
    previous_failure: str | None = None,
) -> str:
    """Assemble the user message for the Verdict call.

    previous_failure: ValidationResult.retry_hint from a failed attempt.
    """
    today = today or date.today()
    parts = [
        f"Today's date: {today.isoformat()}",
        f'<claim id="{_safe_id(claim.id)}" time_sensitivity="{claim.time_sensitivity.value}">',
        _neutralize(claim.text),
        "</claim>",
        "",
        "<evidence>",
    ]

    if evidence.is_empty:
        parts.append("(no evidence was found)")

    for e in evidence.guardian:
        published = e.published_at.date().isoformat() if e.published_at else "unknown"
        parts += [
            f'[{e.id}] {_outlet(e.source_name)} | published: {published} | title: {_neutralize(e.title)}',
            f"passage: {_neutralize(e.passage)}",
            "",
        ]

    for f in evidence.factchecks:
        reviewed = f.reviewed_at.date().isoformat() if f.reviewed_at else "unknown"
        parts += [
            f"[{f.id}] Fact-check by {_neutralize(f.publisher)} | reviewed: {reviewed} | match_score: {f.match_score:.2f}",
            f"claim reviewed: {_neutralize(f.claim_reviewed)}",
            f"rating: {_neutralize(f.raw_rating)}",
            "",
        ]

    parts.append("</evidence>")

    if previous_failure:
        parts += [
            "",
            "## Correction needed",
            previous_failure,
            "Fix these. Quote only exact text from the evidence above, or choose UNVERIFIABLE if no valid quote supports a verdict.",
        ]

    parts += ["", f'Return the verdict for claim_id "{_safe_id(claim.id)}".']
    return "\n".join(parts)


def build_review_user_prompt(
    claim: Claim,
    evidence: RankedEvidence,
    first: ClaimVerdict,
    derived_label: str,
    today: date | None = None,
    problems: list[str] | None = None,
) -> str:
    """User message for the second-opinion call: the verdict prompt plus the first verdict and the label its components imply."""
    base = build_verdict_user_prompt(claim, evidence, today)
    head, _, tail = base.rpartition("\n\nReturn the verdict")
    components = [
        f"- {_neutralize(c.name)} [{c.kind.value}]: {c.status.value}; ids: {_neutralize(', '.join(c.evidence_ids)) or 'none'}"
        for c in first.components
    ] or ["- (none)"]
    return "\n".join([
        head, "", "<first_verdict>",
        f"label: {first.label.value}",
        f"confidence: {first.confidence:.2f}",
        f"answer: {_neutralize(first.answer)}",
        "components:", *components,
        "</first_verdict>", "",
        f"The components imply {derived_label}, but the first label was {first.label.value}. Decide which is right and correct the verdict.",
        *([f"Problems found: {_neutralize('; '.join(problems))}"] if problems else []),
        f'Return the verdict for claim_id "{_safe_id(claim.id)}".',
    ])
