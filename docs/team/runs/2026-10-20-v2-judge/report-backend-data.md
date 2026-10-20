# Report: backend-data
DONE: count_independent (registrable domain, bbc alias, wire credit, identical passage, title Jaccard 0.9, fact-check publishers); tiers.tier_of and a capped +0.03 rerank bonus; web.py publishedTime parsing, 200-char snippet floor, WEB_MAX_RESULTS/WEB_MAX_PASSAGES; search_fn.stats; month-aware Guardian date window; firecrawl fixture and tests.
EVIDENCE (engineer's claim, lead to re-run): pytest 448 passed, 2 skipped (17 new tests).
FINDINGS: two existing test_web.py tests changed for deliberate behaviour changes; wire detection is a regex heuristic; "with Reuters" in a Guardian passage collapses with Reuters.
GAPS: fixture hand-built not live; tier lists are judgement; no test for a month window crossing a year boundary.
BLOCKERS: none
