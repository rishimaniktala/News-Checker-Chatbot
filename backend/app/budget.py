"""Per-run cost and loop guard. Filled in by the data engineer."""

from dataclasses import dataclass, field


@dataclass
class RunBudget:
    max_cost_usd: float
    max_iterations: int
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    queries_seen: set[str] = field(default_factory=set)

    def add_usage(self, model: str, tokens_in: int, tokens_out: int) -> None:
        raise NotImplementedError

    @property
    def exhausted(self) -> bool:
        raise NotImplementedError

    def register_query(self, query: str) -> bool:
        """True if the normalized query is new; False if it was already used."""
        raise NotImplementedError
