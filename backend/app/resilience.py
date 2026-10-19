"""Retry with backoff and a per-API circuit breaker. Filled in by the data engineer."""

from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitOpen(RuntimeError):
    """The API failed repeatedly and is in its cool-down."""

    def __init__(self, api: str):
        super().__init__(f"{api} is temporarily unavailable")
        self.api = api


def call_with_retry(fn: Callable[[], T], *, api: str, retries: int = 2) -> T:
    """Run fn. Retry 429, 5xx and timeouts with exponential backoff and jitter.
    Never retry other 4xx. Raise CircuitOpen while the breaker for `api` is open."""
    raise NotImplementedError
