# Brief for backend-data
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Objective
Implement retrieval and its guards. Real keys are NOT available now, so build against recorded-shape fixtures and mock httpx transports; the lead will run live later.
1. `app/budget.py`: fill in RunBudget. `add_usage` prices tokens from a small per-model dict of USD per 1M tokens (constants with a comment: verify against ai.google.dev/pricing, unverified); unknown model uses a conservative default. `exhausted` is cost_usd >= max_cost_usd. `register_query` normalizes (lowercase, collapse whitespace, strip punctuation) and returns False for repeats.
2. `app/resilience.py`: fill in `call_with_retry`: retry only 429, 5xx, timeouts and connection errors, max `retries`, exponential backoff with jitter (sleep function injectable for tests); never retry other 4xx or ValueError/schema errors; per-api circuit breaker: after 3 consecutive failures the api is open for 30 seconds and calls raise `CircuitOpen` immediately; a success resets it; expose `reset_breakers()` for tests. Detect status from `httpx.HTTPStatusError` and from google-genai `errors.APIError` (has `.code`), without importing google at module import time if avoidable.
3. `app/retrievers/guardian.py`: Guardian Content API client (httpx, key from env GUARDIAN_API_KEY, `show-fields=bodyText,headline`, page-size ~8, order-by relevance), split bodyText into passages of at most ~600 characters on paragraph/sentence boundaries (Guardian terms: do not republish full articles; short passages only). `app/retrievers/factcheck.py`: Google Fact Check Tools `claims:search` client (env FACTCHECK_API_KEY), maps to FactCheckReview. Both go through `call_with_retry`, have an 8-second timeout, return [] plus a recorded "source unavailable" note on CircuitOpen or error rather than raising.
4. `app/retrievers/rerank.py`: score passages 0..1 against the claim. Use Gemini embeddings if `embed_fn` is supplied (injectable `Callable[[list[str]], list[list[float]]]`; cosine in plain Python), else fall back to a deterministic lexical score (token overlap / BM25-lite). Keep top 5 Guardian passages as EvidenceItem (ids E1..), FactCheckReview.match_score from the same scoring against claim_reviewed (F1..).
5. `app/retrievers/search.py`: fill in `make_search_fn(settings, budget)`. Honors `settings.sources`. Per query: skip queries `budget.register_query` rejects. Merge across queries, dedupe by URL, return RankedEvidence(claim_id, attempt=round_no). Expose what was unavailable by adding a list attribute on the returned function, `search_fn.unavailable: list[str]`, so the pipeline can tell the user which source is down.
6. `tests/fixtures/`: guardian_search.json and factcheck_search.json in the real response shapes (hand-built realistic examples, labelled recorded-shape not recorded-live in a README line), plus tests using `httpx.MockTransport`.

## Owned paths
- backend/app/budget.py
- backend/app/resilience.py
- backend/app/retrievers/**
- backend/tests/fixtures/**
- backend/tests/test_budget.py
- backend/tests/test_resilience.py
- backend/tests/test_retrievers.py

## Forbidden paths
Everything else.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Acceptance criteria
- Tests: budget cap and repeat-query block; retry counts per status (429 and 503 retried twice then raised, 400 not retried, timeout retried); breaker opens after 3 failures and recovers after cool-down (inject clock); Guardian 503 degrades to empty with unavailable note; passages never exceed 600 chars; reranking orders a relevant passage above an irrelevant one deterministically; fixtures parse into valid RankedEvidence; settings.sources=("guardian",) never calls Fact Check.
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
About 70 tool calls.
