# Report: security
DONE: 3 test files (injection, ssrf+http-layer+sql+cors, secrets); strict xfail test per confirmed gap; review of main/run/store/inputs/url_safety. No app code touched.
EVIDENCE (engineer's claim, lead to re-run): tests/test_security_*.py -> 125 passed, 2 skipped, 31 xfailed.
FINDINGS: SEC-1 low backslash host; SEC-2 low NAT64/::127.0.0.1; SEC-3 med case-sensitive delimiter neutralize (evidence/claim); SEC-4 med same for <input>; SEC-5 low fullwidth lookalikes; SEC-6 med context_note outside <input> unescaped; SEC-7 med validator accepts verbatim quote of injected sentence; SEC-8 med exception text to SSE/store; SEC-9 med log.exception unredacted; SEC-10 med API keys in query string leak via httpx logs/errors; SEC-11 med no HTTP body-size limit. Untested: /api/runs unauthenticated, no rate/concurrency cap, stop only set at stream end, sqlite conns never closed.
BLOCKERS: none
