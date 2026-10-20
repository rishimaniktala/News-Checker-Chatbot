# Operations

Local-first. There is no hosted deploy. The same files run on a laptop, in Docker Compose and in GitHub Actions.

## Environment

All variables live in `.env` (copy `.env.example`). Real environment values win over `.env`. `GEMINI_MODEL` still works as an alias for `MODEL_PRIMARY`.

| Variable | Default | Purpose |
|---|---|---|
| GEMINI_API_KEY | none | Model calls. Required. |
| GUARDIAN_API_KEY | none | Guardian source. |
| FACTCHECK_API_KEY | none | Fact Check source. |
| FIRECRAWL_API_KEY | none | Web search source. |
| MODEL_PRIMARY | gemini-3.6-flash | Main model. |
| MODEL_FALLBACK | gemini-3.5-flash-lite | Used when the primary fails. |
| PROMPT_VERSION | code default | Recorded on each report. |
| SOURCES | guardian,web,factcheck | Enabled sources. |
| MAX_ITERATIONS | 3 | Retrieval rounds per claim, 1 to 3. |
| MAX_COST_USD_PER_RUN | 0.05 | Per-run cost cap. |
| ENABLE_VALIDATOR | true | Verbatim quote check. |
| WEB_ALLOWED_DOMAINS | built-in list | Web domain allowlist. |
| WEB_MAX_RESULTS | 5 | Results per web search. |
| RATE_LIMIT_PER_MIN | 10 | Per-client request limit. |
| MAX_CONCURRENT_RUNS | 2 | Simultaneous runs. |
| RUNS_TOKEN | empty | Token to read stored runs. |
| RUNS_RETENTION_DAYS | 30 | Age at which runs are deleted. |
| CACHE_TTL_HOURS | 24 | Retrieval cache lifetime. |
| NEWS_DB | backend/runs.db | SQLite path. |
| LOG_LEVEL | INFO | Stdout log level. |

Some of these (rate limit, concurrency, token, retention, cache, log level) are being added by the backend work in this run. Check `backend/app/config.py` for what the current build reads.

## Start and stop

- Laptop: `make dev` runs `dev.sh`. Backend on :8000, frontend on :3000. Ctrl-C stops both. It tells you if the venv or `node_modules` is missing.
- Docker: `make docker-up` (needs a `.env` in the repo root). Stop with Ctrl-C or `docker compose down`. Run history sits in the `runs` volume and survives `down`.
- Checks: `make test`, `make lint`, `make eval-fake`.

`GET /health` answers without calling any dependency. It reports which keys are set, never their values.

## Failure modes

- Source down: that source returns nothing and the run continues on the others. Reports show fewer independent sources and lower confidence. If every source is down the verdict is not enough evidence.
- Model fallback: when the primary model fails after its retries, the call repeats on `MODEL_FALLBACK`. The report sets `fallback_used` and lists `models_used`. Frequent fallback means the primary is overloaded or the key is rate limited.
- Rate limit: callers over `RATE_LIMIT_PER_MIN` get HTTP 429. Wait and retry. Gemini 429s trigger the fallback model first.
- Cache: retrieval results are reused for `CACHE_TTL_HOURS`. If a source looks stale, delete the cache entries or lower the TTL. Cache hits cost no source calls.
- Cost cap: when `MAX_COST_USD_PER_RUN` is hit the run stops retrieving and judges what it has.

## Rotate a key

1. Create the new key at the provider and revoke the old one.
2. Edit `.env`.
3. Restart (`make dev` again, or `docker compose up -d --force-recreate backend`).
4. Check `/health` shows the key as configured.

If a key was ever committed or printed, treat it as leaked and rotate it. CI runs gitleaks on every push.

## Read a stored run

Every run is saved to SQLite (`NEWS_DB`, default `backend/runs.db`). Fetch one with `GET /api/runs/{run_id}`, adding the `RUNS_TOKEN` if one is set. Or open the file directly: `sqlite3 backend/runs.db .tables`.

## Backup and retention

- Back up with `sqlite3 backend/runs.db ".backup runs-backup.db"`. A plain file copy while the app writes can be torn.
- Runs older than `RUNS_RETENTION_DAYS` are deleted. Back up before lowering it.
- `*.db` is git-ignored and docker-ignored.

## Limits

- One process. Run state, the rate limiter and the concurrency counter are in memory. Do not start uvicorn with more than one worker or put two backends behind a balancer. The Dockerfile pins `--workers 1`.
- SQLite is single-writer. Fine at this scale.

## Security

- Local use only. Compose binds ports to 127.0.0.1. Do not expose the backend to a network without TLS and auth in front.
- Set `RUNS_TOKEN` if anyone else can reach the port, since stored runs contain claim text.
- Keys are never logged or returned. Images contain no keys; `.env` is passed at run time and excluded by `.dockerignore`.
- Dependabot opens weekly update PRs for pip, npm and Actions.
