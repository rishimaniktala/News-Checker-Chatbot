# Brief for devops
Project: /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. Read first: docs/superpowers/plans/2026-10-19-news-checker-build.md (architecture), docs/api-contract.md, docs/decision-log.md, backend/app/{llm,agents,orchestrator,rules,prompts,schemas,config,budget,resilience,run,main,store}.py, backend/app/retrievers/*. Pipeline: extract claims -> per claim loop (retrieve Guardian, then reputable web search from round 2, plus Fact Check -> rerank -> evidence check) -> judge -> validator (quotes verbatim) -> consensus -> stream over SSE. Goal of this run (v2): better identification and calibrated confidence, a stronger judge, model fallback (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite), production hardening. Real failures we already fixed and must never regress: "Sweden joined NATO in 2024" (needs the year addressed, not just topic), Bank of England 5.25% in Aug 2023 (do not confuse with the Aug 2024 cut), Musk bought Twitter vs an unrelated "Musk bought Google" fact-check, a 0.77 fact-check about a video flipping a correct verdict, opinions ("X is a dictator") are not fact-checked, vaccines-autism stance misread, keys never in output. Fixed shared interfaces: llm.generate(system, contents, schema, *, role="judge", attempts=2) with roles ocr, extract, evidence, judge, review; llm.begin_run() / llm.current_log() -> RunLog(calls: list[CallRecord(role, model, fallback_used, tokens_in, tokens_out, latency_ms)], .last(role), .models_used, .fallback_used); retrievers.dedupe.count_independent(evidence, evidence_ids=None) -> int; prompts.PROMPT_VERSION (str); env MODEL_PRIMARY (default gemini-3.6-flash), MODEL_FALLBACK (default gemini-3.5-flash-lite), GEMINI_MODEL kept as an alias for the primary.

## Objective
Local-first production hygiene. No deploy target; everything must run on a laptop and in GitHub Actions.
1. .github/workflows/ci.yml: on push and pull_request: job backend (setup-python 3.12, pip install -r backend/requirements.lock, pytest -q from backend/, ruff check if configured), job frontend (setup-node 22, npm ci, lint, test, build in frontend/), job eval-smoke (python eval/run_eval.py --fake ... offline), job secrets (gitleaks action with .gitleaks.toml). Pin actions by major version. No secrets needed in CI (all tests are offline).
2. backend/requirements.lock from the existing venv (pip freeze, read only; keep requirements.txt as the human list), a ruff config (backend/ruff.toml: line length 120, rules E,F,I,B,UP, ignore E501 only where needed) and note that you could not run ruff if it is not installed. Do not edit application source to satisfy lint; list the findings instead.
3. docker-compose.yml, backend/Dockerfile, frontend/Dockerfile (multi-stage, non-root, healthcheck against /health, no keys baked in, .env passed at run time), .dockerignore files. You cannot run docker here: say so and keep the files simple and conventional.
4. Makefile: dev, test, lint, eval-fake, docker-up. Update dev.sh to check the venv and node_modules exist and print a friendly message otherwise.
5. .env.example: document every variable, one comment line each: GEMINI_API_KEY, GUARDIAN_API_KEY, FACTCHECK_API_KEY, FIRECRAWL_API_KEY, MODEL_PRIMARY, MODEL_FALLBACK, PROMPT_VERSION, SOURCES, MAX_ITERATIONS, MAX_COST_USD_PER_RUN, ENABLE_VALIDATOR, WEB_ALLOWED_DOMAINS, WEB_MAX_RESULTS, RATE_LIMIT_PER_MIN, MAX_CONCURRENT_RUNS, RUNS_TOKEN, RUNS_RETENTION_DAYS, CACHE_TTL_HOURS, NEWS_DB, LOG_LEVEL. Defaults: MODEL_PRIMARY=gemini-3.6-flash, MODEL_FALLBACK=gemini-3.5-flash-lite.
6. docs/ops.md runbook: env table, how to start and stop, what each failure looks like (source down, model fallback, rate limit, cache), how to rotate a key, how to read a stored run, backup and retention of runs.db, known single-process assumption, security notes (local only, RUNS_TOKEN).
7. .github/dependabot.yml for pip, npm and github-actions (weekly).

## Owned paths
- .github/**
- docker-compose.yml
- backend/Dockerfile
- frontend/Dockerfile
- .dockerignore
- backend/.dockerignore
- frontend/.dockerignore
- backend/requirements.lock
- backend/ruff.toml
- Makefile
- dev.sh
- .env.example
- .gitleaks.toml
- docs/ops.md

## Forbidden paths
All application source under backend/app, frontend/app|components|lib, eval, tests, docs other than ops.md.

## Acceptance criteria
- Files parse (python -c yaml check is unavailable: validate YAML by eye and with python's json for none; keep conventional). Report what could not be run.
- .env.example lists every variable above.

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
About 50 tool calls.
