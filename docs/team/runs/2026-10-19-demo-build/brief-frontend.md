# Brief for frontend
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Objective
Build the one-page UI in `/Users/suhrudjoshi/News-Checker-Chatbot/frontend` (Next.js App Router + TypeScript + Tailwind; shadcn-style components copied in only if needed, otherwise plain Tailwind). Follow docs/api-contract.md exactly. You cannot run the backend; ship a mock SSE server `frontend/mock/server.mjs` (plain Node, port 8000, CORS for localhost:3000, replays a scripted run with delays, plus an error scenario and a "not enough evidence" scenario) and read the API base URL from `NEXT_PUBLIC_API_BASE` (default http://localhost:8000).
Spec (from the project plan): one page, no routing. Zones: Input (text box, URL field, screenshot drag-and-drop, png/jpg, max 5 MB, sent as base64 JSON); Live trace on the left (streamed lines, spinner while a step runs, tick/cross when done; a failed validator shows a visible "re-asking" line); Verdict card on the right (badge with TEXT label, never color alone; confidence label from the number, e.g. High/Medium/Low computed in code; evidence cards with source, link and the cited quote highlighted by locating the exact span in the passage text; consensus bar "N of M ... " built from consensus.agreement_ratio and the cited counts, computed in code; the disclaimer); Run details drawer (cost, latency, tokens, run id from `done`). Map labels: TRUE "Supported", FALSE "Contradicted", MISLEADING "Misleading", UNVERIFIABLE "Not enough evidence" with a neutral (not error) style.
Technical: read the POST stream with fetch + ReadableStream, parse `data:` lines across chunk boundaries; single useReducer with states idle/running/done/error; Submit disabled while running; Cancel via AbortController; 4 example chips (true claim, false claim, odd claim, Swedish claim); friendly error card for `error` events and network failure/timeout; columns stack on narrow screens; keyboard accessible, visible focus, labels on inputs; render all backend text as text, never HTML (XSS safe).
Put the pure logic (SSE chunk parser, reducer, quote-span locator, confidence label) in plain TS modules under `frontend/lib/` with unit tests using Node's built-in test runner or vitest only if already installed; do not install packages with npm unless the scaffold requires it. You MAY run `npm` inside `frontend/` to scaffold and install dependencies (this is the one exception to the no-install rule; network for npm is allowed).

## Owned paths
- frontend/**

## Forbidden paths
backend/**, docs/**, anything else.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Acceptance criteria
- `npm run build` and `npm run lint` pass; unit tests for parser (split chunks, multiple events per chunk, malformed line), reducer transitions, quote locator (exact span, not found, repeated text) pass.
- With the mock server running, the page shows trace lines arriving one by one and the verdict card; error and not-enough-evidence scenarios render correctly.
- Layout verified at 1280px and 390px widths (describe how you checked).

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

Exception to hard rules: npm network access is allowed for scaffolding in frontend/ only.
## Budget
About 80 tool calls.
