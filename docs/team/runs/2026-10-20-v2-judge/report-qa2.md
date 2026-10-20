# Report: qa (v2)
DONE: 7 v2 test files via the real app with a role-aware V2Gemini fake: fallback matrix, judge e2e, regressions, cache e2e, hardening, 10 new weird cases, web fallback.
EVIDENCE (engineer's claim, lead to re-run): full suite 1019 passed, 2 skipped, 30 xfailed; v2 files alone 261 passed, 3 xfailed.
FINDINGS: BUG-leak-1 low orchestrator.py:262/:104 raw upstream text in failed trace; BUG-judge-1 medium review runs only when label and components disagree, so a nonexistent component evidence id never gets reconciled; BUG-judge-2 medium _evidence_strength ignores citation stance, so TRUE backed only by refuting quotes stays TRUE at 0.70.
GAPS: cache hit shows fallback_used false while models_used lists the backup (needs a ruling); PROMPT_VERSION cannot switch at runtime; battery not run with web/fact-check on; chunked upload untested.
BLOCKERS: none
