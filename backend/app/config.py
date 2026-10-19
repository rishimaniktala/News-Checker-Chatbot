"""Runtime settings read from the environment.

The experiment switches (validator, sources, iterations, cost cap, model) are
env vars so the eval runner can flip them without code edits.
"""

import logging
import os
import re
import traceback
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path) -> None:
    """Copy KEY=value lines from a .env file into os.environ without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file(Path(__file__).resolve().parents[2] / ".env")


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    gemini_model: str
    enable_validator: bool
    sources: tuple[str, ...]
    max_iterations: int
    max_cost_usd_per_run: float


def load_settings() -> Settings:
    sources = tuple(s.strip() for s in os.environ.get("SOURCES", "guardian,web,factcheck").split(",") if s.strip())
    return Settings(
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        enable_validator=_flag("ENABLE_VALIDATOR", True),
        sources=sources or ("guardian",),
        max_iterations=max(1, min(3, int(os.environ.get("MAX_ITERATIONS", "3")))),
        max_cost_usd_per_run=float(os.environ.get("MAX_COST_USD_PER_RUN", "0.05")),
    )


_KEY_PATTERN = re.compile(r"(?i)\b(api-key|key)=[^&\s\"']+|AIza[0-9A-Za-z_-]{20,}")
_SECRET_VARS = ("GEMINI_API_KEY", "GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY")


def redact(text: str) -> str:
    """Replace configured API keys, key-like tokens and api-key query values with [redacted]."""
    text = _KEY_PATTERN.sub("[redacted]", text)
    for name in _SECRET_VARS:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "[redacted]")
    return text


def log_failure(log: logging.Logger, what: str) -> None:
    """Log the current exception with its traceback, keys redacted. Call inside an except block."""
    log.error("%s\n%s", what, redact(traceback.format_exc()))


# httpx logs full request URLs at INFO, and Guardian takes its key in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)
