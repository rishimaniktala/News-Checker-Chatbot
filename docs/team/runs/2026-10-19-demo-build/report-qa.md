# Report: qa
DONE: 40-case weird-input battery through real FastAPI app; failure injection (Guardian 503/401, Fact Check 429, Gemini timeout/429/400/bad JSON/exception, all sources down); fixture integration; loop and cost-cap properties.
EVIDENCE (engineer's claim, lead to re-run): full suite 365 passed, 2 skipped, 39 xfailed.
FINDINGS: BUG-search-1 CRITICAL double register_query (orchestrator.py:90 + search.py:33) so real runs never retrieve; BUG-search-2 medium search_fn.unavailable never surfaced; BUG-orch-1 medium raw exception text in trace; BUG-input-1 low non-string fields reported as internal instead of bad_input.
GAPS: no Firecrawl success path; fake model cannot follow injections; test_retrievers patches time.sleep ineffectively (tests may sleep for real).
BLOCKERS: none
