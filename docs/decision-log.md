# Decision log

One line per decision or result: what, why, evidence.

- 2026-10-19 Local-only, no deploy. Why: demo runs on a laptop; removes CORS and hosting risk. Evidence: PM decision.
- 2026-10-19 Moved agents, rules, schemas and prompts into `backend/app` with relative imports. Why: package layout; no logic changes. Evidence: commit a753d69.
- 2026-10-19 Orchestrator alone blocks repeated queries. Why: search_fn also registered them, so every query looked like a repeat and retrieval never ran. Evidence: BUG-search-1 found by QA, fixed in 7c-level commit "stop double-counting queries".
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
