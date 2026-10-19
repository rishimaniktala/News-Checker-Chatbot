# News Checker Build Plan

**Goal:** a local-only fact-checker app (text, URL, screenshot) with a streamed trace and validated, quoted verdicts.

**Architecture:** FastAPI runs the existing agents in a worker thread; a plain-code orchestrator drives retrieve, evidence-check, verdict, validate, consensus and pushes `TraceEvent`s to an SSE stream. Next.js reads the stream with `fetch`. SQLite stores every run.

**Stack:** Python 3.12, FastAPI, httpx, google-genai, SQLite, Next.js, Tailwind.

**Spec:** CLAUDE.md (pasted by the PM), `docs/api-contract.md`.

## Global constraints
- Local only, no deploy, no CORS beyond `http://localhost:3000`.
- Keys only in server env; never logged, traced or committed.
- Orchestrator is plain code; the judge has no tools; numbers computed by code.
- `schemas.py` is not changed without the lead.
- Cut order if late: cache, other-outlets consensus, OCR.

## Workstreams (parallel, disjoint paths)
| Id | Owner | Paths | Deliverable |
|---|---|---|---|
| A | backend-api | `app/main.py`, `app/run.py`, `app/store.py`, `app/orchestrator.py`, `app/agents.py` | SSE endpoint, failure containment, trace store, settings wiring |
| B | backend-data | `app/budget.py`, `app/resilience.py`, `app/retrievers/**`, `tests/fixtures/**` | RunBudget, retry+breaker, Guardian + Fact Check + rerank |
| C | ai | `app/rules.py`, `eval/**`, `tests/test_rules*.py` | rationale check, validator toggle, eval set + runner |
| D | frontend | `frontend/**` | UI against a mock stream |
| E | dev | `app/url_safety.py`, `app/inputs.py` | SSRF guard, Firecrawl fetch, image limits + OCR glue |

Then: integrate (lead), qa + security adversarial pass, reviewer, lead verifies and fixes.

## Acceptance
- `cd backend && .venv/bin/python -m pytest -q` green.
- `curl -N` on `/api/check` shows incremental `trace` events then `verdict` then `done` (with fakes offline; with keys live).
- UI works at desktop and phone width.
- Weird-input battery and failure injection pass.
