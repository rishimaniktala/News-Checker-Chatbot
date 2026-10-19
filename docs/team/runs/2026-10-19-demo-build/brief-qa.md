# Brief for qa
Project: /Users/suhrudjoshi/News-Checker-Chatbot. Backend is built in backend/app (main.py SSE API, run.py run_check(req, emit, settings, search_fn, budget), orchestrator.py, agents.py, rules.py, inputs.py, url_safety.py, budget.py, resilience.py, retrievers/). Contract: docs/api-contract.md. Spec rules: orchestrator is plain code; judge has no tools; retrieved/scraped text is untrusted (prompt-injection must never be followed); every failure ends in a clean verdict or friendly error, within budget; keys never in logs, traces, store or responses. Existing tests: backend/tests (126 passing). Everything is offline: fake Gemini by monkeypatching app.agents functions or a fake genai client, fake SearchFn, httpx.MockTransport.

## Objective
1. Weird-input battery: `backend/tests/weird_inputs.json` (about 30 cases: id, kind, input, expected: one of verdict|error, notes) and `backend/tests/test_weird_inputs.py` that drives each through the real FastAPI app with TestClient (POST /api/check, parse SSE) using fake agents/search. Cases: empty, whitespace, 20k-char paste, 60k-char paste, emoji only, Swedish, Hindi, Arabic, mixed languages, joke claim, a question, an opinion, two contradictory claims, future event, SQL/HTML/script in input, null bytes, very long single word, wrong JSON shape (missing kind, unknown kind, text not a string, kind=url with no url), unsafe URLs (127.0.0.1, 169.254.169.254, ftp://x, file:///etc/passwd), oversized image, wrong mime, corrupt base64, text-free image (fake OCR illegible), and prompt-injection strings in the text. Assert for every case: stream always ends with a done event; exactly one verdict or error before done; no stack trace text or key-like strings in any event; HTTP 200 stream, never a 500; cost within MAX_COST_USD_PER_RUN.
2. Failure injection (`backend/tests/test_failure_injection.py`): Guardian down (503 forever), Fact Check 429, Gemini timeout, Gemini returning malformed JSON, Gemini raising a generic Exception mid-run, every source down at once. Assert retry counts per error type, the circuit breaker opening, the user-visible degraded message naming which source is unavailable (check search_fn.unavailable reaches the trace; if it does not, that is a finding), and that the result is UNVERIFIABLE rather than a crash or a confident answer.
3. Fixture integration (`backend/tests/test_integration_fixtures.py`): run the real search_fn code against backend/tests/fixtures via httpx.MockTransport, with fake LLM agents, through run_check; assert a validated cited verdict is produced and that every quote is a verbatim substring of a retrieved passage.
4. Loop/cost properties: with a fake LLM that always returns an invalid quote, the run stops at 3 attempts and falls back to UNVERIFIABLE; with always-insufficient evidence it stops at 3 rounds; with MAX_COST_USD_PER_RUN tiny it stops early.

## Owned paths
- backend/tests/weird_inputs.json
- backend/tests/test_weird_inputs.py
- backend/tests/test_failure_injection.py
- backend/tests/test_integration_fixtures.py
- backend/tests/test_loop_properties.py

## Forbidden paths
All of backend/app, frontend, eval, docs. Do not edit existing test files.

## Inputs
Project: /Users/suhrudjoshi/News-Checker-Chatbot. Backend is built in backend/app (main.py SSE API, run.py run_check(req, emit, settings, search_fn, budget), orchestrator.py, agents.py, rules.py, inputs.py, url_safety.py, budget.py, resilience.py, retrievers/). Contract: docs/api-contract.md. Spec rules: orchestrator is plain code; judge has no tools; retrieved/scraped text is untrusted (prompt-injection must never be followed); every failure ends in a clean verdict or friendly error, within budget; keys never in logs, traces, store or responses. Existing tests: backend/tests (126 passing). Everything is offline: fake Gemini by monkeypatching app.agents functions or a fake genai client, fake SearchFn, httpx.MockTransport.

## Acceptance criteria
- New tests pass or are strict xfail with a BUG id; the full suite stays green.

## Hard rules
- No network, no real credentials, never open a real .env, never print env vars.
- No git writes. No package installs; use /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python.
- You write TESTS ONLY, in the owned paths. A real bug in app code is NOT fixed by you: write a strict `pytest.mark.xfail(strict=True, reason="BUG-...")` test that proves it and list it in FINDINGS with file:line and severity.
- Test command from backend/: `.venv/bin/python -m pytest -q`.
- Prose in unslop style (plain, no filler).
## Report shape
Six sections under 350 words: DONE, FILES, EVIDENCE, FINDINGS (one line per bug: id, severity, where, expected vs actual), GAPS, BLOCKERS.
## Budget
About 60 tool calls.
