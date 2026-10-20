"""Confidence from named factors, each 0..1, combined with fixed weights.

The model's own confidence number is not an input: it is the least reliable signal we have.
"""

import json
from pathlib import Path

WEIGHTS = {
    "evidence_strength": 0.30,
    "source_independence": 0.15,
    "corroboration": 0.20,
    "quote_validity": 0.10,
    "judge_agreement": 0.15,
    "model_quality": 0.10,
}
INDEPENDENT_FOR_FULL_SCORE = 3
FALLBACK_MODEL_QUALITY = 0.6
RETRIED_QUOTE_VALIDITY = 0.5
CALIBRATION_FILE = Path(__file__).resolve().parent / "calibration.json"
DEFAULT_CUTOFFS = {"high": 0.75, "medium": 0.5}


def load_cutoffs(path: Path = CALIBRATION_FILE) -> dict[str, float]:
    try:
        raw = json.loads(path.read_text())["cutoffs"]
        high, medium = float(raw["high"]), float(raw["medium"])
    except (OSError, ValueError, KeyError, TypeError):
        return dict(DEFAULT_CUTOFFS)
    return {"high": high, "medium": medium} if 0 <= medium <= high <= 1 else dict(DEFAULT_CUTOFFS)


CONFIDENCE_CUTOFFS = load_cutoffs()


def band(value: float) -> str:
    if value >= CONFIDENCE_CUTOFFS["high"]:
        return "High"
    return "Medium" if value >= CONFIDENCE_CUTOFFS["medium"] else "Low"


def _unit(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_confidence(
    *,
    evidence_strength: float,
    independent_sources: int,
    corroboration: float,
    quote_first_try: bool,
    judge_agreement: float,
    fallback_used: bool,
) -> tuple[float, dict[str, float]]:
    """Returns (confidence, factors). Raising any factor never lowers the confidence."""
    factors = {
        "evidence_strength": _unit(evidence_strength),
        "source_independence": _unit(independent_sources / INDEPENDENT_FOR_FULL_SCORE),
        "corroboration": _unit(corroboration),
        "quote_validity": 1.0 if quote_first_try else RETRIED_QUOTE_VALIDITY,
        "judge_agreement": _unit(judge_agreement),
        "model_quality": FALLBACK_MODEL_QUALITY if fallback_used else 1.0,
    }
    value = sum(WEIGHTS[k] * v for k, v in factors.items())
    return round(_unit(value), 3), {k: round(v, 3) for k, v in factors.items()}
