import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

import pytest  # noqa: E402
from metrics import abstain_rate, accuracy, calibration, macro_f1, p95  # noqa: E402


def test_accuracy():
    assert accuracy(["A", "B", "A"], ["A", "A", "A"]) == pytest.approx(2 / 3)


def test_macro_f1_perfect():
    assert macro_f1(["A", "B"], ["A", "B"]) == 1.0


def test_macro_f1_mixed():
    # A: tp1 fp1 fn0 -> 2/3. B: tp0 -> 0. mean 1/3
    assert macro_f1(["A", "B"], ["A", "A"]) == pytest.approx(1 / 3)


def test_macro_f1_empty():
    assert macro_f1([], []) == 0.0


def test_abstain_rate():
    assert abstain_rate(["UNVERIFIABLE", "TRUE", "TRUE", "UNVERIFIABLE"]) == 0.5


def test_p95_nearest_rank():
    assert p95(list(range(1, 21))) == 19
    assert p95([]) == 0.0


def test_calibration_sorted_high_first():
    assert calibration([0.2, 0.9, 0.5], [True, True, False]) == [(0.9, True), (0.5, False), (0.2, True)]
