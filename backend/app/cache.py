"""Report cache for text checks. Single process; entries live in the SQLite store."""

import hashlib
import os

from . import prompts, store
from .config import load_settings

_PROBLEM_PREFIX = "Source problem"


def ttl_hours() -> float:
    return float(os.environ.get("CACHE_TTL_HOURS", "24"))


def key_for(text: str) -> str:
    """Same text, models, prompts and sources give the same key. Case and spacing do not matter."""
    s = load_settings()
    normalized = " ".join(text.split())
    parts = (normalized, s.model_primary, getattr(prompts, "PROMPT_VERSION", ""), ",".join(sorted(s.sources)))
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def eligible(events: list[dict]) -> bool:
    """A run is cacheable only if no step failed and no source was unavailable."""
    return not any(e.get("type") == "trace" and (e.get("status") == "failed" or
                   str(e.get("message", "")).startswith(_PROBLEM_PREFIX)) for e in events)


def get(text: str) -> dict | None:
    return store.cache_get(key_for(text), ttl_hours())


def put(text: str, report: dict) -> None:
    store.cache_put(key_for(text), report)
