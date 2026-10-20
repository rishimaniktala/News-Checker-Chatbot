"""HTTP API. Stream shape is in docs/api-contract.md.

Assumes one process: runs are threads in this process, and the rate limiter, concurrency cap and
cache hit path keep their state in memory. Run one uvicorn worker. Behind a proxy every client shares
the proxy's address, so the per-IP limit then acts as a global one.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import os
import queue
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from starlette.background import BackgroundTask

from . import cache, llm, logging_setup, store
from .budget import RunBudget
from .config import load_settings, log_failure
from .agents import embed
from .retrievers.search import make_search_fn
from .run import RunInputError, run_check
from .schemas import Step, StepStatus
from .orchestrator import trace

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    logging_setup.setup_logging()
    try:
        removed = store.purge_older_than(float(os.environ.get("RUNS_RETENTION_DAYS", "30")))
        log.info("purged %d old runs", removed)
    except Exception:
        log_failure(log, "startup purge failed")
    yield


app = FastAPI(title="News checker", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Runs-Token"],
                   expose_headers=["Retry-After", "X-Request-ID"])

STREAM_IDLE_SECONDS = 150  # no event for this long means the worker is stuck
MAX_BODY_BYTES = 8_000_000  # 5 MB image as base64 plus headroom


@app.middleware("http")
async def limit_body(request, call_next):
    length = request.headers.get("content-length")
    if length is None and request.headers.get("transfer-encoding"):
        return JSONResponse({"detail": "Send a Content-Length header."}, status_code=411)
    if length is not None and not length.isdigit():
        return JSONResponse({"detail": "Bad Content-Length."}, status_code=400)
    if int(length or 0) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request too large."}, status_code=413)
    return await call_next(request)


_REQUEST_ID = re.compile(r"[\w.-]{1,64}")


@app.middleware("http")
async def request_id_and_access_log(request, call_next):
    given = request.headers.get("x-request-id", "")
    rid = given if _REQUEST_ID.fullmatch(given) else uuid.uuid4().hex[:16]
    logging_setup.request_id.set(rid)
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    log.info("%s %s -> %d in %dms", request.method, request.url.path, response.status_code,
             (time.monotonic() - started) * 1000)
    return response


_buckets: dict[str, list[float]] = {}
_active_runs = 0
_limits_lock = threading.Lock()


def _retry_after_for_rate(ip: str) -> int:
    """0 if the client may start a run now, else seconds until a token is available."""
    per_min = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
    if per_min <= 0:
        return 0
    now = time.monotonic()
    with _limits_lock:
        tokens, last = _buckets.get(ip, [float(per_min), now])
        tokens = min(float(per_min), tokens + (now - last) * per_min / 60)
        if tokens < 1:
            _buckets[ip] = [tokens, now]
            return math.ceil((1 - tokens) * 60 / per_min)
        _buckets[ip] = [tokens - 1, now]
        if len(_buckets) > 10_000:
            for k in [k for k, (_, t) in _buckets.items() if now - t > 60]:
                del _buckets[k]
    return 0


def _take_run_slot() -> bool:
    global _active_runs
    with _limits_lock:
        if _active_runs >= int(os.environ.get("MAX_CONCURRENT_RUNS", "4")):
            return False
        _active_runs += 1
        return True


def _release_run_slot() -> None:
    global _active_runs
    with _limits_lock:
        _active_runs = max(0, _active_runs - 1)


def _too_many(detail: str, retry_after: int) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=429, headers={"Retry-After": str(retry_after)})


INTERNAL_MESSAGE = "Something went wrong on our side. Please try again."


class Cancelled(BaseException):
    """Client went away; unwinds the run past the per-claim exception handlers."""


@app.get("/health")
def health() -> dict:
    keys = {n.removesuffix("_API_KEY").lower(): bool(os.environ.get(n)) for n in
            ("GEMINI_API_KEY", "GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY")}
    settings = load_settings()
    return {"status": "ok", "keys_configured": keys,
            "models": {"primary": settings.model_primary, "fallback": settings.model_fallback}}


@app.get("/ready")
def ready():
    try:
        store.check_writable()
    except Exception:
        log_failure(log, "database is not writable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, x_runs_token: str | None = Header(None)) -> dict:
    """Open when RUNS_TOKEN is unset, which is only safe for local use."""
    token = os.environ.get("RUNS_TOKEN")
    if token and not hmac.compare_digest((x_runs_token or "").encode(), token.encode()):
        raise HTTPException(401, "Unauthorized.")
    run = store.load_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


def _done_event(run_id: str, cost: float, latency_ms: int, tokens_in: int, tokens_out: int,
                models: list[str], fallback: bool, cached: bool = False) -> dict:
    return {"type": "done", "run_id": run_id, "cost_usd": cost, "latency_ms": latency_ms,
            "tokens_in": tokens_in, "tokens_out": tokens_out, "cached": cached,
            "models_used": models, "fallback_used": fallback}


def _cached_report(req: dict) -> tuple[str | None, dict | None]:
    """The text to cache under (text requests only) and a fresh cache entry for it, if any."""
    text = req.get("text") if req.get("kind") == "text" and isinstance(req.get("text"), str) else None
    text = (text or "").strip() or None
    if text is None:
        return None, None
    try:
        return text, cache.get(text)
    except Exception:
        log_failure(log, "cache lookup failed")
        return text, None


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
    cache_text, hit = _cached_report(req)
    try:
        if hit:
            trace(emit, run_id, Step.NORMALIZE, StepStatus.COMPLETED, message="Served from cache")
            report_dict = {**hit, "run_id": run_id}
            emit({"type": "verdict", "report": report_dict})
            latency_ms = int((time.monotonic() - started) * 1000)
            done = _done_event(run_id, 0, latency_ms, 0, 0, hit.get("models_used") or [], False, cached=True)
            events.append(done)
            _save(run_id, req, events, report_dict, 0, latency_ms, [])
            q.put(done)
            return
        settings = load_settings()
        budget.max_cost_usd, budget.max_iterations = settings.max_cost_usd_per_run, settings.max_iterations
        report = run_check({**req, "run_id": run_id}, emit, settings,
                           make_search_fn(settings, budget, embed_fn=embed), budget)
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
    run_log = llm.current_log()
    calls = [vars(c) for c in run_log.calls] if run_log else []
    done = _done_event(run_id, budget.cost_usd, latency_ms, budget.tokens_in, budget.tokens_out,
                       run_log.models_used if run_log else [], run_log.fallback_used if run_log else False)
    events.append(done)
    report_dict = report.model_dump(mode="json") if report else None
    _save(run_id, req, events, report_dict, budget.cost_usd, latency_ms, calls)
    if report_dict and cache_text and cache.eligible(events):
        try:
            cache.put(cache_text, report_dict)
        except Exception:
            log_failure(log, "could not cache the report")
    q.put(done)


def _save(run_id, req, events, report_dict, cost, latency_ms, calls) -> None:
    try:
        store.save_run(run_id, req, events, report_dict, cost, latency_ms, calls)
    except Exception:
        log_failure(log, f"could not save run {run_id}")


def _worker(req: dict, run_id: str, q: queue.Queue, stop: threading.Event, request_id: str) -> None:
    logging_setup.request_id.set(request_id)
    logging_setup.run_id.set(run_id)
    try:
        _work(req, run_id, q, stop)
    finally:
        _release_run_slot()


@app.post("/api/check")
def check(req: dict, request: Request):
    ip = request.client.host if request.client else "unknown"
    if wait := _retry_after_for_rate(ip):
        return _too_many("Too many checks from your address. Please wait a moment.", wait)
    if not _take_run_slot():
        return _too_many("The checker is busy. Please try again shortly.", 5)
    run_id = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    try:
        threading.Thread(target=_worker, args=(req, run_id, q, stop, logging_setup.request_id.get()),
                         daemon=True).start()
    except Exception:
        _release_run_slot()
        raise

    async def stream():
        deadline = time.monotonic() + STREAM_IDLE_SECONDS
        try:
            while True:
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    if await request.is_disconnected():
                        return
                    if time.monotonic() < deadline:
                        await asyncio.sleep(0.05)
                        continue
                    event = _done_event(run_id, 0, 0, 0, 0, [], False)
                deadline = time.monotonic() + STREAM_IDLE_SECONDS
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    return
        finally:
            stop.set()

    return StreamingResponse(stream(), media_type="text/event-stream", background=BackgroundTask(stop.set),
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
