"""Fit High/Medium confidence cutoffs from an eval run and write backend/app/calibration.json.

    python eval/calibrate.py eval/results/v2_primary_run --config v2_primary

Reads <results>/calibration.json (config -> [[confidence, correct], ...]) written by run_eval.py.
A cutoff is the lowest bin edge at which everything at or above it is right at least `target` of the time.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import metrics  # noqa: E402

DEFAULTS = {"high": 0.75, "medium": 0.5}
TARGETS = {"high": 0.9, "medium": 0.7}
MIN_ITEMS = 5
OUT = HERE.parent / "backend" / "app" / "calibration.json"


def fit_cutoffs(confidences, correct, bins=10, min_items=MIN_ITEMS):
    """Cutoffs from reliability bins. A level with too little data keeps its default."""
    edges = [b["lo"] for b in metrics.reliability_bins(confidences, correct, bins)]
    out = dict(DEFAULTS)
    for level, target in TARGETS.items():
        for lo in edges:
            kept = [ok for c, ok in zip(confidences, correct) if c >= lo]
            if len(kept) >= min_items and sum(kept) / len(kept) >= target:
                out[level] = round(lo, 2)
                break
    out["medium"] = min(out["medium"], out["high"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="folder written by run_eval.py")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    pairs = json.loads((Path(a.results) / "calibration.json").read_text())[a.config]
    conf, ok = [p[0] for p in pairs], [bool(p[1]) for p in pairs]
    cutoffs = fit_cutoffs(conf, ok)
    note = f"fitted from {a.config}, n={len(pairs)}, ece={metrics.expected_calibration_error(conf, ok):.3f}"
    Path(a.out).write_text(json.dumps({"cutoffs": cutoffs, "note": note}, indent=2) + "\n")
    print(cutoffs, note)


if __name__ == "__main__":
    main()
