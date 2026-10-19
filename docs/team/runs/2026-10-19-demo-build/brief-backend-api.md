# Brief for backend-api
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Objective
Turn the demo orchestrator into a served, failure-proof pipeline. Streams per docs/api-contract.md.
1. `app/run.py`: `run_check(req: dict, emit: Callable[[dict], None], settings, search_fn, budget) -> FinalReport`. Normalizes text input (url/image kinds call `app.inputs.normalize_url(url)->NormalizedInput` and `app.inputs.normalize_image(image_b64, mime)->NormalizedInput`, written by another engineer; import lazily and fake in tests; both raise `app.inputs.InputError(code, friendly_message)`). Emits `trace` events (TraceEvent fields flattened) for every step start/complete/retry/fail, then returns the report. Each claim runs inside a try/except: any exception, timeout, `AgentError`, or `CircuitOpen` for one claim yields an UNVERIFIABLE ClaimReport with a visible failed trace event and the real reason in the trace, never a crash.
2. Rework `orchestrator.py` minimally: take `emit`, `settings`, `budget`; honor `settings.max_iterations` for both loops, `settings.enable_validator` (off = accept the first verdict unchecked, still emit a trace line saying validator disabled), block repeated queries via `budget.register_query`, stop when `budget.exhausted`. After the validator passes call `rules.check_rationale(verdict, evidence)`; a non-empty list counts as a validation failure and its text goes into the retry hint. Keep Rishi's logic otherwise intact.
3. `agents.py` adapter (smallest possible, flag it in FINDINGS): read model from `config.load_settings().gemini_model` (env overrides still work), and report token usage of each Gemini call to the budget through a module-level `set_usage_sink(callable)` taking (model, tokens_in, tokens_out) from `response.usage_metadata`. Wrap Gemini calls with `resilience.call_with_retry(..., api="gemini")`.
4. `app/main.py`: FastAPI app with `GET /health`, `POST /api/check` (StreamingResponse, run in a worker thread, events through a queue, flush each event; client disconnect stops the run), `GET /api/runs/{run_id}`; CORS only for http://localhost:3000. Request size cap (reject text over 20000 chars politely by truncating deterministically in code with a trace note, images over 5MB with code bad_input). `done` event carries run_id, cost_usd, latency_ms, tokens_in, tokens_out, cached.
5. `app/store.py`: SQLite (path from env `NEWS_DB`, default backend/runs.db) persisting each run as JSON: request, all events, report, cost, latency. `save_run`, `load_run`. Keys must never be stored.
Retrieval comes from `retrievers.search.make_search_fn` (another engineer); in tests use a fake SearchFn and fake agent functions (monkeypatch).

## Owned paths
- backend/app/main.py
- backend/app/run.py
- backend/app/store.py
- backend/app/orchestrator.py
- backend/app/agents.py
- backend/tests/test_run.py
- backend/tests/test_orchestrator.py
- backend/tests/test_api.py
- backend/tests/test_store.py

## Forbidden paths
Everything else, including backend/app/rules.py, budget.py, resilience.py, retrievers/, inputs.py, url_safety.py, frontend/.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Acceptance criteria
- Tests: cap respected (3 search rounds, 3 validator attempts, max_iterations=1 means single shot), fallback to UNVERIFIABLE on repeated validator failure, cost cap stops the loop, repeated query blocked, validator toggle, one claim raising an exception does not stop other claims, malformed-JSON AgentError becomes UNVERIFIABLE with failed trace event.
- Tests with FastAPI TestClient: /health; /api/check streams trace then verdict then done in order; bad input yields error then done; /api/runs/{id} returns the stored run.
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
