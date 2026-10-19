# API contract

The backend and frontend are built against this file. Change it only with the lead.

## POST /api/check

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
| `done` | always last | `run_id, cost_usd, latency_ms, tokens_in, tokens_out, cached` |

Rules:
- Exactly one of `verdict` or `error` precedes `done`.
- `error.code` is one of `bad_input`, `unsafe_url`, `fetch_failed`, `unreadable_image`, `internal`.
- Friendly messages never contain stack traces, keys or raw upstream errors.
- A failed claim still yields a `verdict` with `UNVERIFIABLE` for that claim, plus a `trace` event with `status: failed`.

## GET /health
`{"status": "ok"}`

## GET /api/runs/{run_id}
The stored run: input, every trace event, prompts, tool calls, tokens, cost, latency, validator results.
