# Brief for frontend
Project: /Users/suhrudjoshi/News-Checker-Chatbot, branch feat/v2-judge. Read first: docs/superpowers/plans/2026-10-19-news-checker-build.md (architecture), docs/api-contract.md, docs/decision-log.md, backend/app/{llm,agents,orchestrator,rules,prompts,schemas,config,budget,resilience,run,main,store}.py, backend/app/retrievers/*. Pipeline: extract claims -> per claim loop (retrieve Guardian, then reputable web search from round 2, plus Fact Check -> rerank -> evidence check) -> judge -> validator (quotes verbatim) -> consensus -> stream over SSE. Goal of this run (v2): better identification and calibrated confidence, a stronger judge, model fallback (primary gemini-3.6-flash, fallback gemini-3.5-flash-lite), production hardening. Real failures we already fixed and must never regress: "Sweden joined NATO in 2024" (needs the year addressed, not just topic), Bank of England 5.25% in Aug 2023 (do not confuse with the Aug 2024 cut), Musk bought Twitter vs an unrelated "Musk bought Google" fact-check, a 0.77 fact-check about a video flipping a correct verdict, opinions ("X is a dictator") are not fact-checked, vaccines-autism stance misread, keys never in output. Fixed shared interfaces: llm.generate(system, contents, schema, *, role="judge", attempts=2) with roles ocr, extract, evidence, judge, review; llm.begin_run() / llm.current_log() -> RunLog(calls: list[CallRecord(role, model, fallback_used, tokens_in, tokens_out, latency_ms)], .last(role), .models_used, .fallback_used); retrievers.dedupe.count_independent(evidence, evidence_ids=None) -> int; prompts.PROMPT_VERSION (str); env MODEL_PRIMARY (default gemini-3.6-flash), MODEL_FALLBACK (default gemini-3.5-flash-lite), GEMINI_MODEL kept as an alias for the primary.

## Objective
Make the new backend fields understandable in the UI. Existing look (editorial paper-and-ink, Fraunces/Hanken/Plex Mono, stamp, pipeline rail, wire) stays; add components, no new npm dependencies except if audit fixes require version bumps.
1. lib/types.ts: additive fields: ClaimReport.components[{name, kind, status: supported|contradicted|unknown, evidence_ids, note}], model_used, fallback_used, independent_sources, confidence_factors (record of 0..1), FinalReport.prompt_version, models_used; DoneEvent.models_used, fallback_used. TraceEvent step may be "second_opinion" (add to STEP_NAME: "Getting a second opinion").
2. New components: ComponentTable ("What we checked": one row per part with a text status mark and word, supported/contradicted/unknown with plain explanation, links to the evidence clippings it cites; keyboard friendly), ConfidenceBreakdown (disclosure under the pips: each factor as a labelled bar with a plain-language name and its value, e.g. "Independent outlets", "Quotes verified", "Fact-check agreement", "Judges agreed", "Model quality"; hide missing factors), SourcesBadge ("N independent outlets"), ModelNote (small text "Judged by <model>"; an amber notice when fallback_used: "Backup model used, treat with a little more caution").
3. Receipt: show models_used and a "cached" chip (done.cached) and the prompt version if present. Error card: a friendly 429 message ("Too many checks at once, try again in N seconds" using Retry-After if readable). Cancel and timeout behaviour unchanged.
4. lib/labels.ts: confidence cutoffs as exported constants (High>=0.75, Medium>=0.5 for now); the lead will tune them from the calibration. Keep confidenceLabel(c) signature.
5. Update frontend/mock/server.mjs: add scenarios: components + fallback used + second opinion, and a 429. Keep existing scenarios working.
6. Tests (node --test lib/lib.test.ts plus new lib tests): pure helpers (component status summary, factor labelling, retry-after parsing). Run npm audit; fix high vulnerabilities with non-breaking upgrades only (npm audit fix without --force) and report what remains. You MAY run npm inside frontend/ (network allowed for npm only).
7. a11y: statuses never colour-only, tab order sane, disclosure is a real button with aria-expanded. Verify at 1280 and 390 px using the playwright-core scratch setup at /private/tmp/claude-501/-Users-suhrudjoshi-News-Checker-Chatbot/4f32b75f-0563-4f9e-81a0-e7792999fcfc/scratchpad/pw (chrome channel, headless) against the mock server and view the screenshots.

## Owned paths
- frontend/**

## Forbidden paths
backend/**, docs/**, eval/**, .github/**.

## Acceptance criteria
- npm run lint, npm test and npm run build pass; the new scenarios render at both widths with no console errors and no horizontal overflow.
- npm audit high vulnerabilities fixed or listed with reasons.

## Hard rules
- No network and no real credentials. Never open a real .env (the example file .env.example is fine) or print env vars. Tests use fakes only (monkeypatch llm._get_client with a fake client, httpx.MockTransport for HTTP).
- No git writes. No package installs: use /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python. Missing package -> BLOCKERS.
- Edit only owned paths. A bug elsewhere becomes a finding and a strict xfail test tagged BUG-n.
- Prose, comments and docs in unslop style (plain, no filler, no AI tells). Code in ponytail style: stdlib first, no new frameworks, no speculative abstractions. No inline # comments in function bodies unless the logic is non-obvious.
- schemas.py is already extended by the lead (ComponentCheck, ComponentKind/Status, ClaimReport.components/model_used/fallback_used/independent_sources/confidence_factors, FinalReport.prompt_version/models_used, Step.REVIEW). Do not edit schemas.py; ask the lead in BLOCKERS if you need more.
- Keep the existing suite green: from backend/, `.venv/bin/python -m pytest -q` (currently 431 passed, 2 skipped). If a deliberate behaviour change breaks an existing test in a file you own, update it and list it in FINDINGS.
## Report shape
Six sections under 400 words: DONE, FILES, EVIDENCE (exact command + summary line), FINDINGS, GAPS, BLOCKERS.
Exception to hard rules: npm network access is allowed inside frontend/.
## Budget
About 90 tool calls.
