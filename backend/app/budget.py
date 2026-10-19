"""Per-run cost and loop guard."""

import re
import time
from dataclasses import dataclass, field

# USD per 1M tokens (input, output). Unverified: check ai.google.dev/pricing.
PRICES_PER_M = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
}
DEFAULT_PRICE_PER_M = (1.25, 10.00)


@dataclass
class RunBudget:
    max_cost_usd: float
    max_iterations: int
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    max_seconds: float = 90.0
    queries_seen: set[str] = field(default_factory=set)
    started: float = field(default_factory=time.monotonic)

    def add_usage(self, model: str, tokens_in: int, tokens_out: int) -> None:
        price_in, price_out = PRICES_PER_M.get(model, DEFAULT_PRICE_PER_M)
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += (tokens_in * price_in + tokens_out * price_out) / 1_000_000

    @property
    def exhausted(self) -> bool:
        return self.cost_usd >= self.max_cost_usd or time.monotonic() - self.started >= self.max_seconds

    def register_query(self, query: str, scope: str = "") -> bool:
        """True if the normalized query is new for this scope (a claim id); False if already used."""
        key = scope + "|" + " ".join(re.sub(r"[^\w\s]", " ", query.lower()).split())
        if key in self.queries_seen:
            return False
        self.queries_seen.add(key)
        return True
