# Brief for ai
Project: /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. Read first: docs/superpowers/plans/2026-10-19-news-checker-build.md (architecture), docs/api-contract.md, docs/decision-log.md, backend/app/{llm,agents,orchestrator,rules,prompts,schemas,config,budget,resilience,run,main,store}.py, backend/app/retrievers/*. Pipeline: extract claims -> per claim loop (retrieve Guardian, then reputable web search from round 2, plus Fact Check -> rerank -> evidence check) -> judge -> validator (quotes verbatim) -> consensus -> stream over SSE. Goal of this run (v2): better identification and calibrated confidence, a stronger judge, model fallback (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite), production hardening. Real failures we already fixed and must never regress: "Sweden joined NATO in 2024" (needs the year addressed, not just topic), Bank of England 5.25% in Aug 2023 (do not confuse with the Aug 2024 cut), Musk bought Twitter vs an unrelated "Musk bought Google" fact-check, a 0.77 fact-check about a video flipping a correct verdict, opinions ("X is a dictator") are not fact-checked, vaccines-autism stance misread, keys never in output. Fixed shared interfaces: llm.generate(system, contents, schema, *, role="judge", attempts=2) with roles ocr, extract, evidence, judge, review; llm.begin_run() / llm.current_log() -> RunLog(calls: list[CallRecord(role, model, fallback_used, tokens_in, tokens_out, latency_ms)], .last(role), .models_used, .fallback_used); retrievers.dedupe.count_independent(evidence, evidence_ids=None) -> int; prompts.PROMPT_VERSION (str); env MODEL_PRIMARY (default gemini-3.6-flash), MODEL_FALLBACK (default gemini-3.5-flash-lite), GEMINI_MODEL kept as an alias for the primary.

## Objective
Make the judge and the classification smarter, calibrated and explainable.
1. Versioned prompts: move prompt text to files backend/app/prompt_files/v1/*.md (current text, byte-for-byte) and v2/*.md (new): extraction, verdict, evidence_check, ocr, review. prompts.py loads by PROMPT_VERSION (env PROMPT_VERSION, default "v2") and exports PROMPT_VERSION. Keep the public builder names and neutralize(); existing security tests must keep passing. Fill templates in one pass.
2. v2 verdict prompt + output: the judge fills ClaimVerdict.components (2-5 parts of the claim: who/what/when/quantity/place, each supported|contradicted|unknown with evidence ids). Rules in the prompt: a part is supported only if an item states it for the right time period (use published_at and the dates in the text); topic-only mentions are unknown; absence of evidence is not evidence of absence; a fact-check about a different claim is background only; evidence from a different period than the claim does not count; opinions are not judged. Add few-shot examples built from the real failures listed in the context (Sweden year, Bank of England 2023 vs 2024 cut, Musk/Google, "will not live there" is not "selling"). Keep injection defences (untrusted blocks).
3. backend/app/judge.py (pure code, no LLM): derive_label(components) -> VerdictLabel (TRUE iff >=1 component and all supported; FALSE iff any contradicted with >=1 evidence id; MISLEADING if both supported and contradicted parts exist; else UNVERIFIABLE) and reconcile(verdict, evidence) -> list[str] problems (component evidence ids exist, a TRUE/FALSE label is backed by components and by citations covering them). Wire into the orchestrator: if the judge label differs from the derived label, run ONE second-opinion call (llm role "review", Step.REVIEW trace events) that shows the discrepancy and asks for a corrected verdict; if still different, use the more conservative of the two labels and mark judge_agreement low.
4. backend/app/confidence.py: compute_confidence(...) -> (value: float, factors: dict[str, float]) from named factors: evidence_strength (share of components supported/contradicted with quotes), source_independence (from retrievers.dedupe.count_independent over cited ids), corroboration (matching fact-check agreement, only at >=0.85 match), quote_validity (passed on first attempt), judge_agreement (review step), model_quality (lower when fallback_used). Fixed weights dict plus CONFIDENCE_CUTOFFS for High/Medium/Low loaded from backend/app/calibration.json if present. Replace the old blend in rules.compute_consensus for final_confidence without changing the ConsensusResult shape; fill ClaimReport.confidence_factors. Add eval/calibrate.py that reads eval results JSON and fits cutoffs by reliability bins and writes calibration.json (plus a tiny sample calibration.json with default cutoffs 0.75/0.5).
5. Orchestrator (you own it): set ClaimReport.components, model_used (llm.current_log().last("judge").model), fallback_used, independent_sources, confidence_factors; FinalReport.prompt_version and models_used; trace message after each retrieval round naming counts per source when search_fn exposes .stats (dict like {"guardian":5,"web":3,"factcheck":1}; may be absent). Evidence-check v2: also report which claim components are covered and ask new queries that target the missing component. Pass role= to every llm call in agents.py.
6. Eval: grow eval/claims.json from 24 to >=60 claims (keep ids; add the real failures above as regression cases with a note; stable pre-2025 facts, a few Swedish/Hindi inputs, opinions/predictions labelled UNVERIFIABLE). Extend eval/run_eval.py: expected calibration error and reliability bins, a count of critical swaps (TRUE<->FALSE), per-config model/prompt arms via env (MODEL_PRIMARY, PROMPT_VERSION), cost/latency. Add arms to eval/configs.json: v1_baseline (PROMPT_VERSION=v1, MODEL_PRIMARY=gemini-2.5-flash), v2_primary (v2, gemini-3.6-flash), v2_lite (v2, gemini-3.5-flash-lite). Offline --fake path keeps working. You cannot run live evals; the lead will.
7. Tests (offline, fakes): judge derive/reconcile table, confidence monotonicity and bounds, calibration fitting on toy data, prompt version loading and v1 byte-equality, orchestrator second-opinion path, regression tests for each listed real failure using fake model replies.

## Owned paths
- backend/app/agents.py
- backend/app/prompts.py
- backend/app/prompt_files/**
- backend/app/judge.py
- backend/app/confidence.py
- backend/app/calibration.json
- backend/app/rules.py
- backend/app/orchestrator.py
- eval/**
- backend/tests/test_judge.py
- backend/tests/test_confidence.py
- backend/tests/test_prompts_v2.py
- backend/tests/test_calibration.py
- backend/tests/test_regressions.py
- backend/tests/test_orchestrator.py
- backend/tests/test_rules.py
- backend/tests/test_eval_metrics.py
- backend/tests/test_review_fixes.py

## Forbidden paths
backend/app/{llm,config,budget,resilience,run,main,store,cache}.py, backend/app/retrievers/**, backend/app/schemas.py, frontend/**, .github/**.

## Acceptance criteria
- Every real failure in the context has a regression test that passes; full suite green.
- v1 prompt files reproduce the current prompts exactly (test).
- Second-opinion path, derived-label rule table and confidence bounds tested.

## Hard rules
- No network and no real credentials. Never open a real .env (the example file .env.example is fine) or print env vars. Tests use fakes only (monkeypatch llm._get_client with a fake client, httpx.MockTransport for HTTP).
- No git writes. No package installs: use /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python. Missing package -> BLOCKERS.
- Edit only owned paths. A bug elsewhere becomes a finding and a strict xfail test tagged BUG-n.
- Prose, comments and docs in unslop style (plain, no filler, no AI tells). Code in ponytail style: stdlib first, no new frameworks, no speculative abstractions. No inline # comments in function bodies unless the logic is non-obvious.
- schemas.py is already extended by the lead (ComponentCheck, ComponentKind/Status, ClaimReport.components/model_used/fallback_used/independent_sources/confidence_factors, FinalReport.prompt_version/models_used, Step.REVIEW). Do not edit schemas.py; ask the lead in BLOCKERS if you need more.
- Keep the existing suite green: from backend/, `.venv/bin/python -m pytest -q` (currently 431 passed, 2 skipped). If a deliberate behaviour change breaks an existing test in a file you own, update it and list it in FINDINGS.
## Report shape
Six sections under 400 words: DONE, FILES, EVIDENCE (exact command + summary line), FINDINGS, GAPS, BLOCKERS.
## Budget
About 90 tool calls.
