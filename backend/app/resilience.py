"""Retry with backoff and a per-API circuit breaker."""

import random
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

FAILURE_LIMIT = 3
COOLDOWN_SECONDS = 30.0
BACKOFF_BASE = 0.5

_breakers: dict[str, list[float]] = {}  # api -> [consecutive failures, opened_at]


class CircuitOpen(RuntimeError):
    """The API failed repeatedly and is in its cool-down."""

    def __init__(self, api: str):
        super().__init__(f"{api} is temporarily unavailable")
        self.api = api


def reset_breakers() -> None:
    _breakers.clear()


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
    elif isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)):
        return True
    else:
        code = getattr(exc, "code", None)  # google-genai errors.APIError
    return isinstance(code, int) and (code == 429 or code >= 500)


def call_with_retry(
    fn: Callable[[], T],
    *,
    api: str,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Run fn. Retry 429, 5xx and timeouts with exponential backoff and jitter.
    Never retry other 4xx. Raise CircuitOpen while the breaker for `api` is open."""
    state = _breakers.setdefault(api, [0, 0.0])
    if state[0] >= FAILURE_LIMIT and clock() - state[1] < COOLDOWN_SECONDS:
        raise CircuitOpen(api)
    for attempt in range(retries + 1):
        try:
            result = fn()
        except Exception as exc:
            if not _retryable(exc):
                raise
            if attempt == retries:
                state[0] += 1
                if state[0] >= FAILURE_LIMIT:
                    state[1] = clock()
                raise
            sleep(BACKOFF_BASE * 2**attempt * (1 + random.random()))
        else:
            _breakers.pop(api, None)
            return result
    raise AssertionError("unreachable")
