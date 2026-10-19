# Report: backend-api
DONE: run.py (run_check, input caps, trace events, usage sink), orchestrator (settings/budget/emit, loop caps, repeated query block, cost cap, validator toggle, check_rationale in retry, per-claim containment), agents.py adapter (model from settings, call_with_retry, usage via ContextVar), main.py (/health, /api/check SSE, /api/runs/{id}, CORS localhost:3000), store.py (SQLite).
FILES: backend/app/{main,run,store,orchestrator,agents}.py, backend/tests/test_{run,orchestrator,api,store}.py
EVIDENCE (engineer's claim, lead to re-run): pytest -q -> 124 passed (full suite then); own files 29 passed.
FINDINGS: evidence-check events use Step.RETRIEVE (no dedicated Step); /api/runs/{id} unauthenticated (local only); agents.py edit is a flagged adapter; __main__ demo removed.
GAPS: no per-claim timeout; cached always false; load_settings failure in worker would skip done; agents._call untested with fake client; no HTTP body size cap (413).
BLOCKERS: none
