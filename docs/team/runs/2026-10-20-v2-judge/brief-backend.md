# Brief for backend
Project: /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. Read first: docs/superpowers/plans/2026-10-19-news-checker-build.md (architecture), docs/api-contract.md, docs/decision-log.md, backend/app/{llm,agents,orchestrator,rules,prompts,schemas,config,budget,resilience,run,main,store}.py, backend/app/retrievers/*. Pipeline: extract claims -> per claim loop (retrieve Guardian, then reputable web search from round 2, plus Fact Check -> rerank -> evidence check) -> judge -> validator (quotes verbatim) -> consensus -> stream over SSE. Goal of this run (v2): better identification and calibrated confidence, a stronger judge, model fallback (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite), production hardening. Real failures we already fixed and must never regress: "Sweden joined NATO in 2024" (needs the year addressed, not just topic), Bank of England 5.25% in Aug 2023 (do not confuse with the Aug 2024 cut), Musk bought Twitter vs an unrelated "Musk bought Google" fact-check, a 0.77 fact-check about a video flipping a correct verdict, opinions ("X is a dictator") are not fact-checked, vaccines-autism stance misread, keys never in output. Fixed shared interfaces: llm.generate(system, contents, schema, *, role="judge", attempts=2) with roles ocr, extract, evidence, judge, review; llm.begin_run() / llm.current_log() -> RunLog(calls: list[CallRecord(role, model, fallback_used, tokens_in, tokens_out, latency_ms)], .last(role), .models_used, .fallback_used); retrievers.dedupe.count_independent(evidence, evidence_ids=None) -> int; prompts.PROMPT_VERSION (str); env MODEL_PRIMARY (default gemini-3.6-flash), MODEL_FALLBACK (default gemini-3.5-flash-lite), GEMINI_MODEL kept as an alias for the primary.

## Objective
Model routing with fallback and production hardening of the API.
1. llm.py router: primary from settings.model_primary (MODEL_PRIMARY, default gemini-3.6-flash), fallback settings.model_fallback (default gemini-3.5-flash-lite). generate() tries primary through call_with_retry; if that exhausts on 429/5xx/timeout/connection errors or the primary's circuit is open, or the primary returns schema-invalid output twice, make ONE attempt on the fallback and set CallRecord.fallback_used=True. Never fall back on other 4xx (auth, bad request); on 404 model-not-found do fall back and log loudly. Separate circuit breakers per model (api names "gemini:primary" / "gemini:fallback"). Per-role generation config table: thinking level per role (ocr low, extract low, evidence low, judge medium, review high) via thinking_level for gemini-3.x and thinking_budget for gemini-2.5; unknown or rejected thinking config degrades to none instead of failing. Keep the thinking-token billing fix and the 40 s call timeout. embed() unchanged but also recorded in the log.
2. config.py: add model_primary and model_fallback fields (defaults at the END of Settings so positional construction in existing tests still works), keep gemini_model as a property alias of model_primary. budget.py price table (USD per 1M tokens in/out, list prices): gemini-3.6-flash 1.50/7.50 (introductory half price until 2026-12-31, use list), gemini-3.5-flash-lite 0.30/2.50, gemini-3.5-flash 1.50/9.00, keep the 2.5 entries; a test must fail if any default model has no price.
3. run.py: call llm.begin_run() at the start; emit a trace event when a call fell back ("Switched to the backup model <name>"); the done event gains models_used and fallback_used; stored run includes the call log (role, model, fallback, tokens, latency). Update docs/api-contract.md for the new fields.
4. main.py: per-client-IP rate limit (env RATE_LIMIT_PER_MIN default 20) and a global concurrency cap (MAX_CONCURRENT_RUNS default 4), in-memory token bucket, return 429 JSON with Retry-After BEFORE streaming; X-Request-ID middleware (echo or generate) and JSON structured logging with the existing redaction, include request id and run id; /api/runs/{id} requires header X-Runs-Token when RUNS_TOKEN is set (constant-time compare, 401 otherwise; unset = open, document that this is local-only); /health adds configured model names and key booleans (never values); /ready checks the database is writable; fix client disconnect so the worker stops promptly (set the stop flag when the stream closes before any event); startup purge of runs older than RUNS_RETENTION_DAYS (default 30).
5. cache.py + store.py: cache the final report for kind=text requests keyed by sha256 of normalized input text + model_primary + PROMPT_VERSION + sources; TTL CACHE_TTL_HOURS default 24; cache only runs where no claim failed and no source was unavailable; a hit replays a short trace ("Served from cache") then the stored verdict, with done.cached=true and zero cost. Document the single-process assumption.
6. Tests (offline): router fallback matrix (429, 503, timeout, circuit open, malformed JSON twice, 401 no fallback, 404 fallback), per-model breakers, price table coverage, rate limit and concurrency cap, request-id echo, runs token auth, readiness, cache hit/miss/ineligible, retention purge, disconnect stops worker.

## Owned paths
- backend/app/llm.py
- backend/app/config.py
- backend/app/budget.py
- backend/app/resilience.py
- backend/app/run.py
- backend/app/main.py
- backend/app/store.py
- backend/app/cache.py
- backend/app/logging_setup.py
- docs/api-contract.md
- backend/tests/test_llm_router.py
- backend/tests/test_budget.py
- backend/tests/test_resilience.py
- backend/tests/test_api.py
- backend/tests/test_run.py
- backend/tests/test_store.py
- backend/tests/test_cache.py
- backend/tests/test_ratelimit.py
- backend/tests/test_config.py
- backend/tests/test_failure_injection.py
- backend/tests/test_loop_properties.py
- backend/tests/test_weird_inputs.py
- backend/tests/conftest.py

## Forbidden paths
agents.py, prompts.py, rules.py, orchestrator.py, judge.py, confidence.py, schemas.py, retrievers/**, eval/**, frontend/**.

## Acceptance criteria
- Router fallback matrix passes; unchanged behaviour when the primary works.
- 429 for over-limit and over-cap, with Retry-After; token auth works; readiness works; cache replay works.
- Full suite green; no key or exception text in any new log or event (add a test).

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
