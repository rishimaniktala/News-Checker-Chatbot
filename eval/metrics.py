"""Pure metric functions for the eval runner. No network, no model calls."""

import math


def accuracy(gold: list[str], pred: list[str]) -> float:
    return sum(g == p for g, p in zip(gold, pred)) / len(gold) if gold else 0.0


def macro_f1(gold: list[str], pred: list[str]) -> float:
    """Mean F1 over the labels that appear in gold. A label with no true or
    predicted hits scores 0."""
    labels = sorted(set(gold))
    scores = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def abstain_rate(pred: list[str], abstain_label: str = "UNVERIFIABLE") -> float:
    return pred.count(abstain_label) / len(pred) if pred else 0.0


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def p95(xs: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def calibration(confidences: list[float], correct: list[bool]) -> list[tuple[float, bool]]:
    """(confidence, was_correct) pairs sorted by confidence, high first.
    Plot or bucket these to see whether 0.9 means right nine times in ten."""
    return sorted(zip(confidences, correct), key=lambda t: -t[0])
