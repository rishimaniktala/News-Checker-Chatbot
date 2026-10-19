# Report: ai
DONE: rules.check_rationale (numbers, URLs, quote guard; validate_verdict untouched), eval/claims.json (24 hand-labelled, 8/8/8), eval/run_eval.py + metrics.py (exact label match, no LLM judge, --fake mode), eval/configs.json (4 configs).
FILES: backend/app/rules.py (additive), backend/tests/test_rules.py, backend/tests/test_eval_metrics.py, eval/*
EVIDENCE (engineer's claim, lead to re-run): pytest -q -> 95 passed (full suite then); run_eval.py --fake wrote summary.
FINDINGS: check_rationale misses written number words and numbers copied from the claim; real eval path untested until app.run exists; citation validity n/a when validator off.
GAPS: labels are the engineer's judgement and unchecked against the Guardian; calibration is a raw list.
BLOCKERS: none
