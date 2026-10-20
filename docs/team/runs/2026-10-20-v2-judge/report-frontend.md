# Report: frontend
DONE: types for components/model/fallback/independent_sources/confidence_factors/prompt_version/models_used; ComponentTable, ConfidenceBreakdown, SourcesBadge, ModelNote; Receipt shows models, cached, prompt version; 429 handling via Retry-After; confidence cutoffs as constants; mock server scenarios "second opinion" and "429"; lib/report.ts helpers and 4 tests.
EVIDENCE (engineer's claim, lead to re-run): npm lint clean; npm test 20 pass; npm run build ok; playwright at 1280/390 overflow 0, no console errors. npm audit still 5 high.
FINDINGS: only braces ReDoS via eslint-config-next, fix needs --force (breaking, dev-tooling only), left; guessed confidence_factors keys (independent_sources, quotes_verified, factcheck_agreement, judge_agreement, model_quality) must match backend; browser can read Retry-After only if CORS exposes it; 429 path matches on message prefix "Too many".
GAPS: no component render tests; keyboard path not automated.
BLOCKERS: none
