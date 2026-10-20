# Brief for backend-data
Project: /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. Read first: docs/superpowers/plans/2026-10-19-news-checker-build.md (architecture), docs/api-contract.md, docs/decision-log.md, backend/app/{llm,agents,orchestrator,rules,prompts,schemas,config,budget,resilience,run,main,store}.py, backend/app/retrievers/*. Pipeline: extract claims -> per claim loop (retrieve Guardian, then reputable web search from round 2, plus Fact Check -> rerank -> evidence check) -> judge -> validator (quotes verbatim) -> consensus -> stream over SSE. Goal of this run (v2): better identification and calibrated confidence, a stronger judge, model fallback (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite), production hardening. Real failures we already fixed and must never regress: "Sweden joined NATO in 2024" (needs the year addressed, not just topic), Bank of England 5.25% in Aug 2023 (do not confuse with the Aug 2024 cut), Musk bought Twitter vs an unrelated "Musk bought Google" fact-check, a 0.77 fact-check about a video flipping a correct verdict, opinions ("X is a dictator") are not fact-checked, vaccines-autism stance misread, keys never in output. Fixed shared interfaces: llm.generate(system, contents, schema, *, role="judge", attempts=2) with roles ocr, extract, evidence, judge, review; llm.begin_run() / llm.current_log() -> RunLog(calls: list[CallRecord(role, model, fallback_used, tokens_in, tokens_out, latency_ms)], .last(role), .models_used, .fallback_used); retrievers.dedupe.count_independent(evidence, evidence_ids=None) -> int; prompts.PROMPT_VERSION (str); env MODEL_PRIMARY (default gemini-3.6-flash), MODEL_FALLBACK (default gemini-3.5-flash-lite), GEMINI_MODEL kept as an alias for the primary.

## Objective
Better evidence: independence, source quality and visibility into what each source returned.
1. retrievers/dedupe.py: improve count_independent: collapse by registrable domain (eTLD+1 by simple rule, bbc.co.uk and bbc.com count as the same outlet via a small alias map), collapse syndicated copies (near-identical titles >=0.9 token Jaccard across domains, or wire attribution "Reuters"/"AP"/"AFP" in the passage), identical passages, and fact-check publishers. Keep the signature.
2. retrievers/tiers.py: tier_of(domain) -> 1 (Guardian, wires, public broadcasters, official bodies), 2 (fact-checkers, major papers), 3 (other allowlisted); used by rerank as a small tie-break bonus (at most +0.03, never reorders a clearly more relevant item). Allowlist stays in web.py; keep WEB_ALLOWED_DOMAINS override.
3. web.py: parse publishedTime into a datetime; skip results whose markdown is under 200 chars (snippets); env WEB_MAX_RESULTS (default 6) and WEB_MAX_PASSAGES per page; keep the allowlist and spoof-proof host matching.
4. search.py: expose search_fn.stats = {"guardian": n, "web": n, "factcheck": n} (counts of passages/reviews kept after rerank) updated per call; keep search_fn.unavailable and search_fn.year_hint. Use the month as well as the year for the Guardian date window when a claim names a month and year ("August 2023"): from the first to the last day of that month padded by one month each side; unchanged year-only behaviour; open-search fallback if empty.
5. Fixtures: tests/fixtures/firecrawl_search.json (recorded-shape, with allowlisted and non-allowlisted results, a snippet-only result and a syndicated pair) and tests for all of the above.
6. Check Guardian and Firecrawl terms in code comments: short passages only (<=600 chars), no republishing; keep MAX_PASSAGE.

## Owned paths
- backend/app/retrievers/**
- backend/tests/fixtures/**
- backend/tests/test_retrievers.py
- backend/tests/test_web.py
- backend/tests/test_dedupe.py
- backend/tests/test_tiers.py

## Forbidden paths
Everything else.

## Acceptance criteria
- Dedupe: bbc.co.uk + bbc.com = 1; a Reuters story syndicated to 2 outlets counts 1; two distinct outlets count 2; fact-check publishers counted.
- Month window test; snippet skip test; stats test; full suite green.

## Hard rules
- No network and no real credentials. Never open a real .env (the example file .env.example is fine) or print env vars. Tests use fakes only (monkeypatch llm._get_client with a fake client, httpx.MockTransport for HTTP).
- No git writes. No package installs: use /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python. Missing package -> BLOCKERS.
- Edit only owned paths. A bug elsewhere becomes a finding and a strict xfail test tagged BUG-n.
- Prose, comments and docs in unslop style (plain, no filler, no AI tells). Code in ponytail style: stdlib first, no new frameworks, no speculative abstractions. No inline # comments in function bodies unless the logic is non-obvious.
- schemas.py is already extended by the lead (ComponentCheck, ComponentKind/Status, ClaimReport.components/model_used/fallback_used/independent_sources/confidence_factors, FinalReport.prompt_version/models_used, Step.REVIEW). Do not edit schemas.py; ask the lead in BLOCKERS if you need more.
- Keep the existing suite green: from backend/, `.venv/bin/python -m pytest -q` (currently 431 passed, 2 skipped). If a deliberate behaviour change breaks an existing test in a file you own, update it and list it in FINDINGS.
## Report shape
Six sections under 400 words: DONE, FILES, EVIDENCE (exact command + summary line), FINDINGS, GAPS, BLOCKERS.
## Budget
About 70 tool calls.
