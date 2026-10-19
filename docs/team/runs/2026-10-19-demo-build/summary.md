# Run summary: 2026-10-19-demo-build

## Built
Full local pipeline: text, URL and screenshot input; Guardian and Fact Check retrieval with rerank; evidence check, verdict, validator and consensus loop; SSE API; SQLite trace store; Next.js UI; eval runner; README and decision log.

## Verified by the lead
- `cd backend && .venv/bin/python -m pytest -q` -> 412 passed, 2 skipped (offline, fakes only; scope: whole backend suite).
- `cd frontend && npm test` -> 15 passed (lib modules only); `npm run lint` clean; `npm run build` compiled.
- Smoke: uvicorn started, `/health` ok; a text check without a Gemini key ended with a friendly error then `done`; `http://169.254.169.254/` was rejected as unsafe with a friendly message.
- Scope check after the qa/security phase: exit 0, no violations.

## Not verified
Nothing has run against live Gemini, Guardian, Fact Check or Firecrawl. Response shapes follow public docs. Guardian header-key support, the Gemini thinking config and the model name are unchecked. No eval numbers exist yet. Drag-drop and the image path were not exercised in a browser.

## Corrections applied
Engineer test counts were mid-build and stale; the figures above are the lead's own. Reviewer found 7 must-fix issues after the bug ledger was closed; all fixed in b3d52b9. `bugs.jsonl` `fix_commit` fields say "see git log" rather than a hash.

## Open risks
Instruction-like quote check may reject a legitimate quote. Unauthenticated `/api/runs/{id}`. No rate cap on `/api/check`. DNS rebinding window with Firecrawl. Cancel stops the worker only at its next event.

## Decisions for the PM
1. Provide the four API keys so the lead can run the live acceptance tests (true, false, obscure claim) and the first eval.
2. Decide whether to add the Gemini embedding wrapper (better rerank, one more API call) or keep lexical.
