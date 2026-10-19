# Brief for dev
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Objective
Input handling and the SSRF guard. No keys now; mock everything.
1. `app/url_safety.py`: `check_url(url: str) -> str` returns the normalized URL or raises `UnsafeUrl(friendly_message)`. Allow only http/https. Reject empty, over 2000 chars, userinfo in the URL, non-standard ports other than 80/443/8080/8443, and any host that resolves (use socket.getaddrinfo, check ALL addresses) to loopback, private, link-local, multicast, reserved or unspecified ranges, IPv4 and IPv6, including IPv4-mapped IPv6, decimal/hex/octal IP encodings, and localhost names. Resolver injectable for tests. Messages are friendly, e.g. "That link points to a private or internal address, so I won't fetch it."
2. `app/inputs.py`: `class InputError(Exception)` with `.code` (one of bad_input, unsafe_url, fetch_failed, unreadable_image) and friendly `.message`; `normalize_url(url) -> NormalizedInput`: runs check_url, fetches via Firecrawl REST scrape (httpx, env FIRECRAWL_API_KEY, 20 s timeout, markdown format, the injectable transport for tests), wrapped in `resilience.call_with_retry(..., api="firecrawl")` (module exists, being filled by another engineer; import it normally and in tests inject a pass-through if needed), caps returned text at 20000 chars (truncate in code), maps paywall/empty/404/PDF/oversized responses to InputError("fetch_failed", friendly), and treats the page text as untrusted data. `normalize_image(image_b64, mime) -> NormalizedInput`: allow only image/png and image/jpeg, base64-decode safely, cap 5 MB, verify magic bytes match the declared type, call `app.agents.run_ocr` (inject for tests), and if `is_legible` is false or text empty raise InputError("unreadable_image", "I couldn't read any text in that image. Try a sharper screenshot.").
3. Tests with fakes only: private ranges and encodings, ftp/file/javascript schemes, userinfo, DNS-rebinding style multi-address hosts (one public + one private), redirect target not followed blindly (Firecrawl does the fetching; assert you never fetch the URL directly yourself), oversized and wrong-magic images, illegible OCR, truncation at 20000 chars.

## Owned paths
- backend/app/url_safety.py
- backend/app/inputs.py
- backend/tests/test_url_safety.py
- backend/tests/test_inputs.py

## Forbidden paths
Everything else.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot (read CLAUDE-style spec summary in docs/superpowers/plans/2026-10-19-news-checker-build.md and the SSE contract in docs/api-contract.md). Existing code in backend/app: schemas.py (contracts), prompts.py, agents.py (Gemini calls: run_ocr, extract_claims, check_evidence, give_verdict), rules.py (validate_verdict, consensus, rollup), orchestrator.py (check_claim/check_input loop; currently a demo with a fake search_fn), config.py (Settings), plus interface stubs budget.py, resilience.py, retrievers/search.py.

## Acceptance criteria
- `http://127.0.0.1`, `http://169.254.169.254`, `ftp://x`, `http://[::1]`, `http://2130706433` are all rejected with friendly messages; a normal https URL passes (fake resolver returning a public IP).
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
About 50 tool calls.
