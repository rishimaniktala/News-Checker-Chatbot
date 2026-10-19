# Brief for reviewer

## Objective
Independent audit of the news-checker build on branch feat/integration (repo /Users/suhrudjoshi/News-Checker-Chatbot). Read the engineers' reports (report-*.md in this folder), docs/api-contract.md, docs/superpowers/plans/2026-10-19-news-checker-build.md, then the code in backend/app, eval/, and frontend/ (app, components, lib). Find: claims in reports with no evidence; bugs the tests bless (tests asserting wrong behavior); contract drift between backend events and frontend types; spec violations (orchestrator must be plain code, judge has no tools, numbers computed by code, loop guards, validator semantics, per-error retries, SSRF, keys never leaked); dead code and over-engineering; thread-safety/races in run.py/main.py/store.py/resilience.py; anything that would break on first contact with real APIs (Guardian/Fact Check/Firecrawl/Gemini response shapes, model name defaults, google-genai SDK usage, usage_metadata handling). Run the test suite with /Users/suhrudjoshi/News-Checker-Chatbot/backend/.venv/bin/python -m pytest -q from backend/ (read-only use) and `git log` for history.

## Owned paths
- none

## Forbidden paths
Everything. You write nothing.

## Acceptance criteria
- Findings list, ranked by severity, each with file:line, what is wrong, evidence, and a suggested fix. Separate "must fix before demo" from "nice to have".

## Hard rules
- No network, no credentials, never open real .env. No git writes. No installs.

## Report shape
Six sections under 450 words: DONE, FILES, EVIDENCE, FINDINGS, GAPS, BLOCKERS.
