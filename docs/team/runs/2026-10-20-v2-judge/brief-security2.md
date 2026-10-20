# Brief for security
Project /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. v2 just landed: llm.py router (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite, per-model breakers), v2 prompts in backend/app/prompt_files/v1|v2 loaded by PROMPT_VERSION, judge.py + confidence.py + second-opinion step in orchestrator.py, components in ClaimVerdict, web search fallback (retrievers/web.py, allowlist), dedupe/tiers, cache.py + store tables, rate limit/concurrency cap/request id/JSON logs/X-Runs-Token/readiness/retention in main.py, .github/workflows/ci.yml, Dockerfiles, docker-compose.yml. Read docs/api-contract.md, docs/ops.md, the reports in docs/team/runs/2026-10-20-v2-judge/report-*.md and the code. Existing tests show the fake-model patterns (tests/test_failure_injection.py FakeGemini, tests/test_weird_inputs.py, tests/test_security_*.py).

## Objective
Re-audit the new surface with adversarial tests and a written review; no fixes.
1. Prompt loading: PROMPT_VERSION and any env-driven file path (path traversal such as ../../etc/passwd, absolute paths, empty, unicode) must never read outside backend/app/prompt_files; test load_prompt.
2. Injection through the new inputs: web search results (title, markdown body, source_name, url with closing tags, case variants, fullwidth lookalikes) must stay inside untrusted blocks and cannot close them; the review (second-opinion) prompt built from model output and evidence is also delimited; components fields (name, note) cannot inject into later prompts; instruction-like quotes rejected in the review path too; an injected "TRUE" with no valid quote still ends UNVERIFIABLE.
3. Secrets and logs: sentinel keys must never appear in JSON logs, request-id headers, X-Request-ID echo (header injection with newlines), the stored call log, the cache table, the done event, /health, /ready, error bodies, or exception text from the router (fallback path included).
4. Auth and abuse: X-Runs-Token compare is constant-time (use hmac.compare_digest check in code review), 401 body fixed; rate limit cannot be bypassed with spoofed X-Forwarded-For when not behind a proxy; concurrency cap releases slots on disconnect and on exceptions (no slot leak); oversized and chunked bodies; unicode normalisation tricks in cache keys (two visually different texts must not collide; case/whitespace normalisation must not merge different claims); cache poisoning (one run's report cannot be served for a different text).
5. Links in the UI data: evidence URLs from web results with javascript:/data: schemes must be dropped by the backend or never rendered as links (check retrievers/web.py and frontend components/Evidence.tsx by reading; report).
6. SSRF and URL input unchanged but re-run the existing tests mentally for regressions introduced by web.py (Firecrawl results are never fetched by us).
7. Infra files review (read only, findings only): .github/workflows/ci.yml (permissions least privilege, pull_request_target misuse, pinned actions, secrets exposure to forks), docker-compose.yml, backend/Dockerfile, frontend/Dockerfile (non-root, no baked secrets, ports bound to localhost, base image pinning), .gitleaks.toml, .env.example (no real values).
8. Dependency review: backend/requirements.lock and frontend/package.json for known-risky or unneeded packages (read only).

## Owned paths
- backend/tests/test_sec2_prompts.py
- backend/tests/test_sec2_injection.py
- backend/tests/test_sec2_secrets.py
- backend/tests/test_sec2_abuse.py

## Forbidden paths
All app code, frontend, eval, docs, existing test files, infra files.

## Hard rules
- No network, no real credentials, never open a real .env, never print env vars. Fakes only (monkeypatch app.llm._get_client, httpx.MockTransport).
- No git writes. No installs: use /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python.
- You write TESTS ONLY in the owned paths. A real bug in app code is NOT fixed by you: write a strict xfail test (reason "BUG-... / SEC-...") and list it in FINDINGS with file:line, severity, expected vs actual.
- Run from backend/: .venv/bin/python -m pytest -q (currently 576 passed, 2 skipped).
- Prose in unslop style.
## Report shape
Six sections under 400 words: DONE, FILES, EVIDENCE, FINDINGS (one line per bug), GAPS, BLOCKERS.
## Budget
About 70 tool calls.
