"""Run the golden claims through the pipeline once per config.

    python eval/run_eval.py --claims eval/claims.json --configs eval/configs.json --out eval/results/

Scoring is exact label match. No LLM judge is used. --fake swaps in an offline
stub so the script and its output can be checked without network or keys.
"""

import argparse
import csv
import json
import os
import sys
import time
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

import metrics  # noqa: E402

FIELDS = ["config", "n", "accuracy", "macro_f1", "abstain_rate", "citation_validity",
          "mean_cost_usd", "mean_latency_s", "p95_latency_s", "errors"]


def fake_run_check(req, emit, settings, search_fn, budget):
    from app.schemas import (Claim, ClaimReport, ConsensusResult, FinalReport,
                             NormalizedInput, InputType, VerdictLabel)
    text = req["text"]
    label = list(VerdictLabel)[zlib.crc32(text.encode()) % 3 + 0]
    claim = Claim(id="c1", text=text, checkworthy=True, search_queries=[text])
    cons = ConsensusResult(claim_id="c1", final_label=label, final_confidence=0.6,
                           agreement_ratio=1.0, single_source=True)
    budget.cost_usd = 0.001
    return FinalReport(
        run_id="fake", input=NormalizedInput(input_type=InputType.TEXT, text=text),
        overall_label=label, overall_confidence=0.6, answer="fake",
        claims=[ClaimReport(claim=claim, label=label, confidence=0.6, answer="fake",
                            reasoning="fake", consensus=cons, attempts=1)])


def run_one(claim, env, run_check, make_search):
    from app.budget import RunBudget
    from app.config import load_settings
    with mock.patch.dict(os.environ, env):
        settings = load_settings()
    budget = RunBudget(settings.max_cost_usd_per_run, settings.max_iterations)
    start = time.perf_counter()
    row = {"id": claim["id"], "gold": claim["label"], "pred": "ERROR", "confidence": 0.0,
           "first_attempt_valid": None, "error": None}
    try:
        report = run_check({"kind": "text", "text": claim["claim"]}, lambda *_: None,
                           settings, make_search(settings, budget), budget)
        row["pred"] = report.overall_label.value
        row["confidence"] = report.overall_confidence
        if settings.enable_validator and report.claims:
            row["first_attempt_valid"] = all(c.attempts == 1 for c in report.claims)
    except Exception as e:
        row["error"] = type(e).__name__
    row["latency_s"] = round(time.perf_counter() - start, 3)
    row["cost_usd"] = budget.cost_usd
    row["correct"] = row["pred"] == row["gold"]
    return row


def summarise(name, rows):
    gold = [r["gold"] for r in rows]
    pred = [r["pred"] for r in rows]
    valid = [r["first_attempt_valid"] for r in rows if r["first_attempt_valid"] is not None]
    lat = [r["latency_s"] for r in rows]
    return {
        "config": name, "n": len(rows),
        "accuracy": round(metrics.accuracy(gold, pred), 3),
        "macro_f1": round(metrics.macro_f1(gold, pred), 3),
        "abstain_rate": round(metrics.abstain_rate(pred), 3),
        "citation_validity": round(sum(valid) / len(valid), 3) if valid else "n/a",
        "mean_cost_usd": round(metrics.mean([r["cost_usd"] for r in rows]), 5),
        "mean_latency_s": round(metrics.mean(lat), 3),
        "p95_latency_s": round(metrics.p95(lat), 3),
        "errors": sum(r["error"] is not None for r in rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True)
    ap.add_argument("--configs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fake", action="store_true", help="offline stub, no network")
    a = ap.parse_args()

    data = json.loads(Path(a.claims).read_text())
    claims = data["claims"]
    configs = json.loads(Path(a.configs).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.fake:
        run_check, make_search = fake_run_check, lambda s, b: None
    else:
        from app.run import run_check
        from app.retrievers.search import make_search_fn as make_search

    summaries, calib = [], {}
    for name, env in configs.items():
        rows = [run_one(c, env, run_check, make_search) for c in claims]
        (out / name).mkdir(exist_ok=True)
        for r in rows:
            (out / name / f"{r['id']}.json").write_text(json.dumps(r, indent=2))
        summaries.append(summarise(name, rows))
        calib[name] = metrics.calibration([r["confidence"] for r in rows], [r["correct"] for r in rows])

    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(summaries)

    models = sorted({c.get("GEMINI_MODEL", "default") for c in configs.values()})
    md = [f"Eval set: {a.claims} ({len(claims)} claims). Models: {', '.join(models)}."
          + (" FAKE STUB RUN, numbers are meaningless." if a.fake else ""), "",
          "| " + " | ".join(FIELDS) + " |", "|" + "---|" * len(FIELDS)]
    md += ["| " + " | ".join(str(s[k]) for k in FIELDS) + " |" for s in summaries]
    md += ["", "## Calibration (confidence, correct)", ""]
    md += [f"- {n}: " + ", ".join(f"({c:.2f},{int(ok)})" for c, ok in pairs) for n, pairs in calib.items()]
    (out / "summary.md").write_text("\n".join(md) + "\n")
    (out / "calibration.json").write_text(json.dumps(calib))
    print("\n".join(md))


if __name__ == "__main__":
    main()
