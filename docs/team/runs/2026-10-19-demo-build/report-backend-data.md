# Report: backend-data
DONE: RunBudget (unverified prices), call_with_retry with per-API breaker (3 failures, 30s), Guardian and Fact Check clients degrade to [] with an unavailable note, rerank (cosine if embed_fn else lexical), make_search_fn(settings, budget, embed_fn=None, client=None) with search_fn.unavailable.
FILES: backend/app/{budget,resilience}.py, backend/app/retrievers/{guardian,factcheck,rerank,search}.py, backend/tests/fixtures/*, backend/tests/test_{budget,resilience,retrievers}.py
EVIDENCE (engineer's claim, lead to re-run): pytest -q -> 88 passed (full suite then).
FINDINGS: breaker state is module-global and not thread-safe; 4xx from Guardian also degrades to [] with note; extra optional kwargs on call_with_retry and make_search_fn.
GAPS: nothing run live; no Gemini embed_fn wrapper; fact-check field names (textualRating, claimReview) unverified; passages per article capped at 20; orchestrator not yet wired.
BLOCKERS: none
