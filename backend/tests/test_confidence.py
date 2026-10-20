import itertools
import json

import pytest

from app import confidence
from app.confidence import WEIGHTS, band, compute_confidence, load_cutoffs

BASE = dict(evidence_strength=0.5, independent_sources=1, corroboration=0.5,
            quote_first_try=False, judge_agreement=0.5, fallback_used=True)


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_bounds_over_extremes():
    for es, n, co, q, ja, fb in itertools.product((-1, 0, 1, 5), (0, 1, 9), (0, 1), (True, False), (0, 1), (True, False)):
        value, factors = compute_confidence(evidence_strength=es, independent_sources=n, corroboration=co,
                                            quote_first_try=q, judge_agreement=ja, fallback_used=fb)
        assert 0.0 <= value <= 1.0
        assert all(0.0 <= v <= 1.0 for v in factors.values())
        assert set(factors) == set(WEIGHTS)


@pytest.mark.parametrize("name, better", [
    ("evidence_strength", 1.0), ("independent_sources", 3), ("corroboration", 1.0),
    ("quote_first_try", True), ("judge_agreement", 1.0), ("fallback_used", False),
])
def test_each_factor_raises_confidence(name, better):
    low, _ = compute_confidence(**BASE)
    high, _ = compute_confidence(**{**BASE, name: better})
    assert high > low


def test_best_case_is_one_and_fallback_lowers_model_quality():
    best = dict(evidence_strength=1, independent_sources=3, corroboration=1, quote_first_try=True,
                judge_agreement=1, fallback_used=False)
    assert compute_confidence(**best)[0] == 1.0
    assert compute_confidence(**{**best, "fallback_used": True})[1]["model_quality"] < 1.0


def test_cutoffs_default_when_file_missing_or_bad(tmp_path):
    assert load_cutoffs(tmp_path / "none.json") == {"high": 0.75, "medium": 0.5}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"cutoffs": {"high": 0.4, "medium": 0.6}}))
    assert load_cutoffs(bad) == {"high": 0.75, "medium": 0.5}


def test_cutoffs_read_from_file(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"cutoffs": {"high": 0.8, "medium": 0.55}}))
    assert load_cutoffs(f) == {"high": 0.8, "medium": 0.55}


def test_shipped_calibration_file_matches_defaults():
    assert load_cutoffs() == {"high": 0.75, "medium": 0.5}


def test_band(monkeypatch):
    monkeypatch.setattr(confidence, "CONFIDENCE_CUTOFFS", {"high": 0.75, "medium": 0.5})
    assert [band(0.9), band(0.75), band(0.5), band(0.2)] == ["High", "High", "Medium", "Low"]
