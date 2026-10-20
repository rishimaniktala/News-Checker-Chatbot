import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

import pytest  # noqa: E402
from calibrate import DEFAULTS, fit_cutoffs  # noqa: E402
from metrics import critical_swaps, expected_calibration_error, reliability_bins  # noqa: E402


def test_bins_count_and_accuracy():
    bins = reliability_bins([0.95, 0.91, 0.15], [True, False, False])
    assert [(b["lo"], b["n"], b["accuracy"]) for b in bins] == [(0.1, 1, 0.0), (0.9, 2, 0.5)]


def test_confidence_one_lands_in_top_bin():
    assert reliability_bins([1.0], [True])[0]["hi"] == 1.0


def test_ece_zero_when_calibrated_and_gap_when_not():
    assert expected_calibration_error([0.5, 0.5], [True, False]) == pytest.approx(0.0)
    assert expected_calibration_error([0.9] * 4, [False] * 4) == pytest.approx(0.9)
    assert expected_calibration_error([], []) == 0.0


def test_critical_swaps_only_counts_true_false_flips():
    gold = ["TRUE", "FALSE", "TRUE", "UNVERIFIABLE", "MISLEADING"]
    pred = ["FALSE", "TRUE", "UNVERIFIABLE", "TRUE", "FALSE"]
    assert critical_swaps(gold, pred) == 2


def test_fit_raises_high_cutoff_when_low_bins_are_unreliable():
    conf = [0.95] * 10 + [0.85] * 10 + [0.65] * 10
    ok = [True] * 10 + [True] * 9 + [False] + [True] * 5 + [False] * 5
    assert fit_cutoffs(conf, ok) == {"high": 0.8, "medium": 0.6}


def test_fit_keeps_defaults_with_too_little_data():
    assert fit_cutoffs([0.9, 0.2], [True, False]) == DEFAULTS


def test_fit_lowers_cutoffs_when_model_is_underconfident():
    fitted = fit_cutoffs([0.6] * 10, [True] * 10)
    assert fitted == {"high": 0.6, "medium": 0.6}
