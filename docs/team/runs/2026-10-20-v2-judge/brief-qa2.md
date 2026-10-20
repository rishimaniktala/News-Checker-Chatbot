# Brief for qa
Project /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. v2 just landed: llm.py router (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite, per-model breakers), v2 prompts in backend/app/prompt_files/v1|v2 loaded by PROMPT_VERSION, judge.py + confidence.py + second-opinion step in orchestrator.py, components in ClaimVerdict, web search fallback (retrievers/web.py, allowlist), dedupe/tiers, cache.py + store tables, rate limit/concurrency cap/request id/JSON logs/X-Runs-Token/readiness/retention in main.py, .github/workflows/ci.yml, Dockerfiles, docker-compose.yml. Read docs/api-contract.md, docs/ops.md, the reports in docs/team/runs/2026-10-20-v2-judge/report-*.md and the code. Existing tests show the fake-model patterns (tests/test_failure_injection.py FakeGemini, tests/test_weird_inputs.py, tests/test_security_*.py).

## Objective
Adversarial and regression tests for v2, end to end through the real FastAPI app with fakes.
1. Fallback matrix at API level: primary 429/503/timeout/malformed twice -> the stream still ends with a verdict, a "backup model" trace line, done.fallback_used true, models_used lists the fallback; 401 -> friendly error and no fallback call; both models down -> UNVERIFIABLE not a crash; breaker per model opens after 3 failures and recovers.
2. Judge pipeline: fake replies in the v2 components format: (a) judge says TRUE but a component is unknown (Sweden year missing) -> second-opinion call happens, final is not TRUE; (b) TRUE vs FALSE mismatch -> UNVERIFIABLE; (c) components empty (v1 prompt) -> review skipped; (d) review disagrees again -> more conservative label and judge_agreement 0; (e) confidence never exceeds 0.70 for one outlet, and can exceed it for two independent outlets; (f) quote that reads like an injected instruction rejected.
3. Regression set through the full app (fake replies): Sweden 2024, Bank of England Aug 2023 vs the 2024 cut, Musk Twitter vs an unrelated Musk-Google fact-check, a 0.77 fact-check about a video must not flip a verdict, opinion claim ("X is a dictator") -> nothing to check with the reason, vaccines stance, key never in any event or log.
4. Cache end to end: identical text twice -> second is served from cache with done.cached true, cost 0 and no model call; a run with a source-unavailable note or a failed claim is NOT cached; URL and image kinds never cached; different PROMPT_VERSION or MODEL_PRIMARY -> miss; TTL expiry -> miss.
5. Hardening: rate limit 429 with Retry-After before streaming; concurrency cap; X-Request-ID echoed and generated; /api/runs token auth (401 without, 200 with, unset = open); /ready; retention purge removes old runs only; client disconnect stops the worker; CORS exposes Retry-After.
6. The existing 40-case weird-input battery must still pass; add 10 new cases (very long claim with 6 numbers, claim in Hindi with a year, "Nothing to check" opinions, prediction, claim with a url inside, empty components reply, reply with 7 components, reply with unknown component status, duplicate citations, model reply that is valid JSON but wrong schema).
7. Web fallback: allowlist spoofing (evil.example/https://bbc.com), youtube/quora dropped, Firecrawl 402/429/500 degrade with a "web search" note in the trace, web only used from round 2 or when the Guardian is empty.

## Owned paths
- backend/tests/test_v2_fallback.py
- backend/tests/test_v2_judge_e2e.py
- backend/tests/test_v2_regressions_e2e.py
- backend/tests/test_v2_cache_e2e.py
- backend/tests/test_v2_hardening.py
- backend/tests/test_v2_weird_inputs.py
- backend/tests/test_v2_web.py

## Forbidden paths
All app code, frontend, eval, docs, existing test files.

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
