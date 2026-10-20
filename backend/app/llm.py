"""Gemini access: client, structured-output calls, usage reporting and embeddings.

Every model call in the app goes through generate(). agents.py owns what to ask,
this file owns how the call is made.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from .config import load_settings
from .resilience import CircuitOpen, call_with_retry, retryable

log = logging.getLogger(__name__)
_usage_sink: ContextVar[Optional[Callable[[str, int, int], None]]] = ContextVar("usage_sink", default=None)


@dataclass
class CallRecord:
    role: str
    model: str
    fallback_used: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class RunLog:
    """Every model call made while serving one run, newest last."""

    calls: list[CallRecord] = field(default_factory=list)

    def last(self, role: str) -> CallRecord | None:
        return next((c for c in reversed(self.calls) if c.role == role), None)

    @property
    def models_used(self) -> list[str]:
        return list(dict.fromkeys(c.model for c in self.calls if c.role != "embed"))

    @property
    def fallback_used(self) -> bool:
        return any(c.fallback_used for c in self.calls)


_run_log: ContextVar[RunLog | None] = ContextVar("run_log", default=None)


def begin_run() -> RunLog:
    """Start a fresh call log for the current run (thread/context scoped)."""
    log = RunLog()
    _run_log.set(log)
    return log


def current_log() -> RunLog | None:
    return _run_log.get()


def set_usage_sink(sink: Optional[Callable[[str, int, int], None]]) -> None:
    """Report (model, tokens_in, tokens_out) of each Gemini call to `sink`.
    Scoped to the calling thread's context, so parallel runs do not mix."""
    _usage_sink.set(sink)


T = TypeVar("T", bound=BaseModel)


class AgentError(RuntimeError):
    """The model failed to return valid output after retries."""


# ------------------------------------------------------------ Gemini helper

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Create the Gemini client on first use (reads GEMINI_API_KEY)."""
    global _client
    if _client is None:
        _client = genai.Client(http_options=types.HttpOptions(timeout=CALL_TIMEOUT_MS))
    return _client


_CONFIG_FIELDS = types.GenerateContentConfig.model_fields
CALL_TIMEOUT_MS = 40_000
PRIMARY, FALLBACK = "gemini:primary", "gemini:fallback"
ROLE_THINKING = {"ocr": "low", "extract": "low", "evidence": "low", "judge": "medium", "review": "high"}
_BUDGET_TOKENS = {"low": 512, "medium": 1024, "high": 2048}


def _thinking_config(model: str, role: str = "evidence") -> types.ThinkingConfig | None:
    """Gemini 2.5 takes a token budget, newer models a level. Unknown or older SDKs get none."""
    level = ROLE_THINKING.get(role, "low")
    if model.startswith("gemini-2.5"):
        return types.ThinkingConfig(thinking_budget=_BUDGET_TOKENS[level])
    if "thinking_level" in types.ThinkingConfig.model_fields:
        return types.ThinkingConfig(thinking_level=level)
    return None


def _billed_output_tokens(usage) -> int:
    """Thinking tokens are billed as output but reported separately."""
    return (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)


def _build_config(system: str, schema: type[BaseModel], model: str, role: str = "evidence",
                  think: bool = True) -> types.GenerateContentConfig:
    """Request settings: system prompt + JSON output in `schema`'s shape.
    Written to work across google-genai versions."""
    cfg: dict = {"system_instruction": system, "response_mime_type": "application/json"}
    if "response_json_schema" in _CONFIG_FIELDS:
        cfg["response_json_schema"] = schema.model_json_schema()
    else:  # older SDK versions
        cfg["response_schema"] = schema
    if think and (thinking := _thinking_config(model, role)):
        cfg["thinking_config"] = thinking
    return types.GenerateContentConfig(**cfg)


def _send(model: str, system: str, contents, schema: type[BaseModel], role: str):
    """One request. A rejected thinking config is dropped and the request repeated once."""
    try:
        config = _build_config(system, schema, model, role)
        return _get_client().models.generate_content(model=model, contents=contents, config=config)
    except Exception as e:
        if getattr(e, "code", None) != 400 or "think" not in str(e).lower():
            raise
        config = _build_config(system, schema, model, role, think=False)
        return _get_client().models.generate_content(model=model, contents=contents, config=config)


def _record(role: str, model: str, fallback: bool, response, started: float) -> None:
    usage = getattr(response, "usage_metadata", None)
    tokens_in = (usage.prompt_token_count or 0) if usage else 0
    tokens_out = _billed_output_tokens(usage) if usage else 0
    if (run_log := current_log()) is not None:
        run_log.calls.append(CallRecord(role, model, fallback, tokens_in, tokens_out,
                                        int((time.monotonic() - started) * 1000)))
    if (sink := _usage_sink.get()) and usage:
        sink(model, tokens_in, tokens_out)


def _run(api: str, model: str, system: str, contents, schema: type[T], role: str, attempts: int) -> T:
    last_error: Exception | None = None
    for _ in range(attempts):
        started = time.monotonic()
        response = call_with_retry(lambda: _send(model, system, contents, schema, role), api=api)
        _record(role, model, api == FALLBACK, response, started)
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as e:
            last_error = e
    raise AgentError(f"{schema.__name__}: model gave no valid output after {attempts} attempts: {last_error}")


def _use_fallback(exc: Exception) -> bool:
    """Outages, rate limits and a missing model switch models. Auth and bad requests do not."""
    return isinstance(exc, (AgentError, CircuitOpen)) or retryable(exc) or getattr(exc, "code", None) == 404


def generate(system: str, contents, schema: type[T], *, role: str = "judge", attempts: int = 2) -> T:
    """Call Gemini and parse the reply into `schema`.

    The primary model gets `attempts` tries at valid output (this includes the validators in
    schemas.py, e.g. a TRUE verdict with no citations). If it is down, rate limited, missing or
    keeps returning invalid output, the fallback model gets one try.
    """
    settings = load_settings()
    try:
        return _run(PRIMARY, settings.model_primary, system, contents, schema, role, attempts)
    except Exception as e:
        if not _use_fallback(e) or settings.model_fallback == settings.model_primary:
            raise
        level = log.error if getattr(e, "code", None) == 404 else log.warning
        level("primary model %s failed (%s), trying %s", settings.model_primary,
              type(e).__name__, settings.model_fallback)
    return _run(FALLBACK, settings.model_fallback, system, contents, schema, role, 1)


EMBED_MODEL = "gemini-embedding-001"


def embed(texts: list[str]) -> list[list[float]]:
    """Embedding vectors for reranking. Raises on failure; rerank falls back to lexical scoring."""
    started = time.monotonic()
    response = call_with_retry(
        lambda: _get_client().models.embed_content(model=EMBED_MODEL, contents=texts), api="gemini")
    if (run_log := current_log()) is not None:
        run_log.calls.append(CallRecord("embed", EMBED_MODEL, latency_ms=int((time.monotonic() - started) * 1000)))
    return [e.values for e in response.embeddings]
