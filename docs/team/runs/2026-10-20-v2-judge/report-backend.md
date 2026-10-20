# Report: backend
DONE: llm.py router (primary, one fallback attempt on 429/5xx/timeout/open circuit/two invalid replies/404; none on 400/401/403), per-role thinking table, per-model breakers; config model_primary/model_fallback; price table plus coverage test; run.py begin_run and backup-model trace; main.py rate limit, concurrency cap, X-Request-ID, JSON logs, X-Runs-Token, /ready, /health models, startup purge, async disconnect polling; cache.py and store tables; contract doc.
EVIDENCE (engineer's claim, lead to re-run): pytest 574 passed, 2 skipped; ruff not installed.
FINDINGS: failure-injection fixture pins primary=fallback; conftest gives per-test NEWS_DB and disables the rate limit; models_used includes the embedding model; cache hit path is in main._work; rate limit keys on request.client.host (global behind a proxy).
GAPS: no end-to-end cache-eligibility test with a failed step; disconnect test uses a fake ASGI receive; chunked bodies uncapped.
BLOCKERS: none
