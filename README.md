# News Checker

Paste a claim, a news URL or a screenshot. The app returns a verdict (Supported, Contradicted, Misleading or Not enough evidence), a confidence label, evidence cards with verbatim quotes, and a live trace of every step.

The Guardian and published fact-checks are used as evidence, not as ground truth. "Not enough evidence" is a normal answer.

## How it works

    input (text | URL | screenshot)
      -> normalize: URL -> SSRF check -> Firecrawl; image -> Gemini OCR
      -> extract up to 3 claims (Gemini, structured JSON)
      -> per claim, up to 3 rounds:
           retrieve (Guardian; from round 2 also reputable web search; Fact Check) -> rerank -> evidence check
      -> verdict (Gemini, no tools) -> validator (plain code) -> consensus
      -> streamed to the browser over SSE

Control flow is plain Python in `backend/app/orchestrator.py`. The validator checks that every quote appears verbatim in the cited passage, that every number and link in the answer comes from the evidence, and that quotes do not read like injected instructions. Two failed validations fall back to "Not enough evidence".

## Run it locally

You need Python 3.12, Node 20+, and four API keys.

    cp .env.example .env        # then fill in the keys
    cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cd ../frontend && npm install
    cd .. && ./dev.sh           # backend :8000, frontend :3000

Open http://localhost:3000.

Check one claim from the terminal:

    cd backend && .venv/bin/python -m app.cli "The Bank of England raised rates in 2022"

## Settings (env vars)

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | model for all LLM calls |
| `ENABLE_VALIDATOR` | `true` | turn the validator off for ablations |
| `SOURCES` | `guardian,web,factcheck` | evidence sources: The Guardian first, reputable web search as a fallback, Fact Check last |
| `WEB_ALLOWED_DOMAINS` | built-in list | comma-separated outlets the web fallback may quote (news agencies, public broadcasters, fact-checkers, official bodies) |
| `MAX_ITERATIONS` | `3` | 1 = single shot, 3 = retrieval and validator loops |
| `MAX_COST_USD_PER_RUN` | `0.05` | hard stop for one run |

## Tests and evaluation

    cd backend && .venv/bin/python -m pytest -q          # offline, fakes only
    cd frontend && npm test && npm run lint && npm run build
    python eval/run_eval.py --claims eval/claims.json --configs eval/configs.json --out eval/results/

The eval set in `eval/claims.json` is hand-written by the team (24 claims). Scoring is exact label match with no LLM judge.

## Known limitations

- The Guardian covers news, not every topic; many true claims will come back "Not enough evidence".
- Keyword search misses paraphrases. Reranking helps but does not fix it.
- Gemini can misread evidence. The validator catches fake quotes, not wrong reasoning.
- Consensus is agreement between a model verdict and a fact-check, not truth.
- Runs are stored unauthenticated in a local SQLite file. Local use only.
- Pages are fetched by Firecrawl; we check the URL first but cannot pin its DNS.
