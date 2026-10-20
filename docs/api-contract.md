# API contract

The backend and frontend are built against this file. Change it only with the lead.

## POST /api/check
Limits, applied before any streaming starts: `RATE_LIMIT_PER_MIN` per client IP (default 20, 0 turns it off) and `MAX_CONCURRENT_RUNS` at once (default 4). Over either, the response is `429` JSON `{"detail": ...}` with a `Retry-After` header in seconds. Both are in memory, so they assume one server process. Behind a proxy every client shares the proxy's address.


Request (JSON):

    {"kind": "text",  "text": "..."}
    {"kind": "url",   "url": "https://..."}
    {"kind": "image", "image_b64": "...", "mime": "image/png"}

Response: `text/event-stream`. Each message is one line `data: <json>` followed by a blank line.
Every JSON object has a `type` field.

| type | when | other fields |
|---|---|---|
| `trace` | a step starts, finishes, retries or fails | a `TraceEvent` from `schemas.py`, flattened: `run_id, step, status, claim_id, message, payload, ts` |
| `verdict` | once, at the end | `report`: a `FinalReport` from `schemas.py` |
| `error` | the run could not produce a report | `message` (friendly, safe to show), `code` |
| `done` | always last | `run_id, cost_usd, latency_ms, tokens_in, tokens_out, cached, models_used, fallback_used` |

Rules:
- Exactly one of `verdict` or `error` precedes `done`.
- `error.code` is one of `bad_input`, `unsafe_url`, `fetch_failed`, `unreadable_image`, `internal`.
- Friendly messages never contain stack traces, keys or raw upstream errors.
- `models_used` lists every model that answered a call in the run (the embedding model included). `fallback_used` is true if any call went to the backup model; a `trace` event "Switched to the backup model <name>" is sent the first time each backup model answers.
- `cached: true` means the report was replayed from the cache: a trace "Served from cache", the stored `verdict`, then `done` with zero cost and tokens. Only `kind: "text"` requests are cached, for `CACHE_TTL_HOURS` (default 24), and only when no step failed and no source was unavailable. The key covers the normalized text, primary model, prompt version and sources.
- A failed claim still yields a `verdict` with `UNVERIFIABLE` for that claim, plus a `trace` event with `status: failed`.

Every response carries `X-Request-ID`. A client-sent value matching `[\w.-]{1,64}` is echoed, anything else is replaced.

## GET /health
`{"status": "ok", "keys_configured": {"gemini": bool, ...}, "models": {"primary": str, "fallback": str}}` (key booleans only, never values). Does not touch the database.

## GET /ready
`{"status": "ready"}`, or `503 {"status": "unavailable"}` if the database cannot take a write.

## GET /api/runs/{run_id}
The stored run: input, every trace event, tokens, cost, latency, and `calls`, the model call log (`role, model, fallback_used, tokens_in, tokens_out, latency_ms`).
When `RUNS_TOKEN` is set, the request needs a matching `X-Runs-Token` header or gets `401`. When it is unset the endpoint is open, which is only acceptable for local use. Runs older than `RUNS_RETENTION_DAYS` (default 30) are deleted at startup.
