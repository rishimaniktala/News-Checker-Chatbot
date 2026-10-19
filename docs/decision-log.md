# Decision log

One line per decision or result: what, why, evidence.

- 2026-10-19 Local-only, no deploy. Why: demo runs on a laptop; removes CORS and hosting risk. Evidence: PM decision.
- 2026-10-19 Moved agents, rules, schemas and prompts into `backend/app` with relative imports. Why: package layout; no logic changes. Evidence: commit a753d69.
- 2026-10-19 Orchestrator alone blocks repeated queries. Why: search_fn also registered them, so every query looked like a repeat and retrieval never ran. Evidence: BUG-search-1 found by QA, fixed in the commit "stop double-counting queries".
- 2026-10-19 Rerank uses a lexical score by default, Gemini embeddings only if an `embed_fn` is passed. Why: one fewer API dependency and deterministic tests. Not yet measured against embeddings.
- 2026-10-19 Delimiter neutralizing folds NFKC and matches closers case-insensitively with any spacing, replacing them with `[/tag]`. Why: SEC-3/4/5 showed `</EVIDENCE>` and fullwidth variants closed the data block. Evidence: tests in test_security_injection.py.
- 2026-10-19 OCR context note is wrapped in its own untrusted `<context_note>` block. Why: it was placed outside the data tags (SEC-6).
- 2026-10-19 `check_rationale` rejects quotes that read like instructions. Why: a verbatim quote of an injected sentence passed the quote check (SEC-7). Risk: may reject a legitimate quote that contains a phrase like "must answer true"; the retry then falls back to Not enough evidence.
- 2026-10-19 Fact Check key moved to the `X-Goog-Api-Key` header; Guardian key stays in the query string, with httpx request logging silenced and status errors rewritten without the URL. Why: SEC-10. Guardian header support is unverified.
- 2026-10-19 Exceptions are redacted for keys before they reach the trace, the store or the logs. Why: SEC-8/9.
- 2026-10-19 Request bodies over 8 MB get HTTP 413 before parsing. Why: SEC-11. Limit trusts Content-Length.
- 2026-10-19 Eval set is 24 claims hand-written by the team, not Venky's set. Labels are the engineer's judgement and are unchecked against the Guardian. Spot-check before quoting numbers.

## Experiments
None run yet. They need API keys: see `eval/configs.json` for the four configs.
- 2026-10-19 Reviewer found seven must-fix issues; all fixed with tests in `test_review_fixes.py`: `check_rationale` now allows numbers from the claim, publication years and the current year (R1); fact-check match uses Jaccard when no embeddings (R2) so a long review containing every claim word no longer scores 1.0 and overrides the verdict; thinking tokens count toward cost (R3); thinking config chosen by model name, `thinking_budget=512` for 2.5 (R4); settings load inside the try so a bad env value still ends the stream (R5); repeat-query block is per claim (R6); a 90 s run deadline plus a 40 s Gemini call timeout (R7).
- 2026-10-19 Known and left: low-severity dead code (unused `should_retry`, `reset_breakers` outside tests, duplicate size constants), `link_is_alive` is never passed so the LINK_DEAD check does not run, and cancelling a request stops the worker only at its next event.
- 2026-10-19 Added Firecrawl web search as a secondary source, used only from round 2 or when the Guardian finds nothing, and limited to an allowlist of reputable outlets (`WEB_ALLOWED_DOMAINS`). Why: the Guardian alone returned "Not enough evidence" for claims it covered thinly (Buckingham Palace). A live search returned YouTube, Quora and a magazine, so unfiltered web results are not acceptable evidence. Cost: Firecrawl credits per search result; limited to 6 results and fallback rounds only.
- 2026-10-19 Fact-check match threshold raised 0.75 -> 0.85. Why: "Sweden joined NATO in 2024" was flipped to Misleading by a fact-check about a video of the Swedish army (match 0.77). Evidence: test_a_loosely_matching_fact_check_does_not_override_the_verdict.
- 2026-10-19 Fact-check publisher falls back to the site name when the API gives none (was "Unknown").
