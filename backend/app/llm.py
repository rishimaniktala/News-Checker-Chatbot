"""Gemini access: client, structured-output calls, usage reporting and embeddings.

Every model call in the app goes through generate(). agents.py owns what to ask,
this file owns how the call is made.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from .config import load_settings
from .resilience import call_with_retry

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
        return list(dict.fromkeys(c.model for c in self.calls))

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


def _thinking_config(model: str) -> types.ThinkingConfig | None:
    """Gemini 2.5 takes a token budget, newer models a level. Unknown or older SDKs get none."""
    if model.startswith("gemini-2.5"):
        return types.ThinkingConfig(thinking_budget=512)
    if "thinking_level" in types.ThinkingConfig.model_fields:
        return types.ThinkingConfig(thinking_level="low")
    return None


def _billed_output_tokens(usage) -> int:
    """Thinking tokens are billed as output but reported separately."""
    return (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)


def _build_config(system: str, schema: type[BaseModel], model: str) -> types.GenerateContentConfig:
    """Request settings: system prompt + JSON output in `schema`'s shape.
    Written to work across google-genai versions."""
    cfg: dict = {"system_instruction": system, "response_mime_type": "application/json"}
    if "response_json_schema" in _CONFIG_FIELDS:
        cfg["response_json_schema"] = schema.model_json_schema()
    else:  # older SDK versions
        cfg["response_schema"] = schema
    if thinking := _thinking_config(model):
        cfg["thinking_config"] = thinking
    return types.GenerateContentConfig(**cfg)


def generate(system: str, contents, schema: type[T], *, role: str = "judge", attempts: int = 2) -> T:
    """Call Gemini and parse the reply into `schema`.

    Retries once if the reply is malformed or breaks a schema rule (this
    includes the validators in schemas.py, e.g. a TRUE verdict with no citations).
    """
    last_error: Exception | None = None
    tries = 0
    started = time.monotonic()
    while tries < attempts:
        model = load_settings().gemini_model
        config = _build_config(system, schema, model)
        response = call_with_retry(
            lambda: _get_client().models.generate_content(model=model, contents=contents, config=config),
            api="gemini",
        )
        tries += 1
        log = current_log()
        if log is not None:
            usage_md = getattr(response, "usage_metadata", None)
            log.calls.append(CallRecord(
                role=role, model=model,
                tokens_in=(usage_md.prompt_token_count or 0) if usage_md else 0,
                tokens_out=_billed_output_tokens(usage_md) if usage_md else 0,
                latency_ms=int((time.monotonic() - started) * 1000)))
        sink, usage = _usage_sink.get(), getattr(response, "usage_metadata", None)
        if sink and usage:
            sink(model, usage.prompt_token_count or 0, _billed_output_tokens(usage))
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as e:
            last_error = e
    raise AgentError(f"{schema.__name__}: model gave no valid output after {attempts} attempts: {last_error}")


EMBED_MODEL = "gemini-embedding-001"


def embed(texts: list[str]) -> list[list[float]]:
    """Embedding vectors for reranking. Raises on failure; rerank falls back to lexical scoring."""
    response = call_with_retry(
        lambda: _get_client().models.embed_content(model=EMBED_MODEL, contents=texts), api="gemini")
    return [e.values for e in response.embeddings]
