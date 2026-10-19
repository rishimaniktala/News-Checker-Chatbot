"""HTTP API. Stream shape is in docs/api-contract.md.

Assumes one process: runs are threads in this process and nothing is shared between processes.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import store
from .budget import RunBudget
from .config import load_settings, log_failure
from .retrievers.search import make_search_fn
from .run import RunInputError, run_check

log = logging.getLogger(__name__)

app = FastAPI(title="News checker")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

STREAM_IDLE_SECONDS = 150  # no event for this long means the worker is stuck
MAX_BODY_BYTES = 8_000_000  # 5 MB image as base64 plus headroom


@app.middleware("http")
async def limit_body(request, call_next):
    # ponytail: trusts Content-Length; a chunked upload without one is not capped
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request too large."}, status_code=413)
    return await call_next(request)


INTERNAL_MESSAGE = "Something went wrong on our side. Please try again."


class Cancelled(BaseException):
    """Client went away; unwinds the run past the per-claim exception handlers."""


@app.get("/health")
def health() -> dict:
    keys = {n.removesuffix("_API_KEY").lower(): bool(os.environ.get(n)) for n in
            ("GEMINI_API_KEY", "GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY")}
    return {"status": "ok", "keys_configured": keys}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.load_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


def _work(req: dict, run_id: str, q: queue.Queue, stop: threading.Event) -> None:
    events: list[dict] = []
    started = time.monotonic()
    budget = RunBudget(0.05, 3)

    def emit(event: dict) -> None:
        if stop.is_set():
            raise Cancelled
        events.append(event)
        q.put(event)

    report = None
    try:
        settings = load_settings()
        budget.max_cost_usd, budget.max_iterations = settings.max_cost_usd_per_run, settings.max_iterations
        report = run_check({**req, "run_id": run_id}, emit, settings,
                           make_search_fn(settings, budget), budget)
        emit({"type": "verdict", "report": report.model_dump(mode="json")})
    except Cancelled:
        return
    except RunInputError as e:
        report = None
        emit({"type": "error", "message": e.message, "code": e.code})
    except Exception:
        log_failure(log, f"run {run_id} failed")
        report = None
        emit({"type": "error", "message": INTERNAL_MESSAGE, "code": "internal"})

    latency_ms = int((time.monotonic() - started) * 1000)
    done = {"type": "done", "run_id": run_id, "cost_usd": budget.cost_usd, "latency_ms": latency_ms,
            "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out, "cached": False}
    events.append(done)
    try:
        store.save_run(run_id, req, events, report.model_dump(mode="json") if report else None,
                       budget.cost_usd, latency_ms)
    except Exception:
        log_failure(log, f"could not save run {run_id}")
    q.put(done)


@app.post("/api/check")
def check(req: dict) -> StreamingResponse:
    run_id = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    threading.Thread(target=_work, args=(req, run_id, q, stop), daemon=True).start()

    def stream():
        try:
            while True:
                try:
                    event = q.get(timeout=STREAM_IDLE_SECONDS)
                except queue.Empty:
                    event = {"type": "done", "run_id": run_id, "cost_usd": 0, "latency_ms": 0,
                             "tokens_in": 0, "tokens_out": 0, "cached": False}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    return
        finally:
            stop.set()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
