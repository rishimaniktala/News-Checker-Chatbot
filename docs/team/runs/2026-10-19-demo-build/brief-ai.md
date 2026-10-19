# Brief for ai
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Objective
1. In `app/rules.py` fill in `check_rationale(verdict, evidence) -> list[str]` (signature fixed, a stub exists): return human-readable problems when (a) a number in verdict.answer or verdict.reasoning does not appear in any evidence text (passages, titles, claim_reviewed; compare normalized digits, tolerate thousands separators and written forms like 5% vs 5 percent), (b) a URL in answer or reasoning is not one of the retrieved urls, (c) a non-UNVERIFIABLE verdict's citations do not include at least one quote (schemas already enforces; keep as a cheap guard). Years such as the number in "in 2025" count as numbers. Do not change validate_verdict's signature or behavior; add tests for it too (fake quote, unknown id, missing quote).
2. Hand-write the eval set `eval/claims.json`: 24 labelled claims, 8 TRUE, 8 FALSE, 8 UNVERIFIABLE (obscure or unfalsifiable), each `{"id","claim","label","note"}`, using claims that were stable facts before 2025 (so the Guardian can settle them); mark the file in a top-level `"_provenance"` field as hand-written by the team, not Venky's set.
3. `eval/run_eval.py`: CLI `python eval/run_eval.py --claims eval/claims.json --configs eval/configs.json --out eval/results/`. Configs are dicts of env overrides (ENABLE_VALIDATOR, SOURCES, MAX_ITERATIONS, MAX_COST_USD_PER_RUN, GEMINI_MODEL). For each config it runs each claim through `app.run.run_check` (being written by another engineer: signature `run_check(req: dict, emit, settings, search_fn, budget) -> FinalReport`; import lazily, accept `--fake` to use an injected stub for tests) and writes per-claim JSON plus a summary table (CSV and Markdown): accuracy, macro-F1, abstain rate (UNVERIFIABLE share), citation validity (validator pass rate on first attempt), mean cost, mean and p95 latency, and a confidence-vs-correct list for calibration. If any LLM-as-judge scoring is added, print a loud warning that it needs a human spot-check; prefer exact label match with no LLM judge. Include `eval/configs.json` with the four report configs (baseline single-shot guardian only; plus factcheck; plus loop; plus validator).
4. `tests/test_eval_metrics.py`: unit tests for the metric functions (macro-F1, calibration list) with tiny inputs, no network.

## Owned paths
- backend/app/rules.py (additive only, except filling check_rationale)
- eval/**
- backend/tests/test_rules.py
- backend/tests/test_eval_metrics.py

## Forbidden paths
Everything else, including prompts.py and schemas.py.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Acceptance criteria
- Tests cover fake number, fake URL, missing quote, clean pass, and number formatting variants; metrics tests; `python eval/run_eval.py --fake ...` runs offline and writes the summary.
- `.venv/bin/python -m pytest -q` green for your files.

## Hard rules
- No network and no real credentials. Never open real `.env` files (`.env.example` is fine) or print environment variables. Tests use fakes and fixtures only.
- No git writes. Reading git is fine.
- No package installs. Use the existing venv: `/Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python`. If you need a package that is missing, say so in BLOCKERS.
- Edit only owned paths. A bug elsewhere becomes a finding plus a strict expected-failure test.
- Comments sparse, plain, human; no inline # comments in function bodies unless the logic is non-obvious. Code in ponytail style: stdlib first, no new frameworks, no speculative abstractions.
- Do not change backend/app/schemas.py. Do not rewrite prompts.py.
- Test command (from /Users/suhrudjoshi/News-Checker-Chatbot/backend): `.venv/bin/python -m pytest -q`. Imports are `from app.x import ...`.

## Report shape
Six sections under 350 words: DONE, FILES, EVIDENCE (exact command + summary line), FINDINGS, GAPS, BLOCKERS.

## Budget
About 60 tool calls.
