"""Retrieval entry point. Filled in by the data engineer."""

from typing import Callable

from ..budget import RunBudget
from ..config import Settings
from ..schemas import Claim, RankedEvidence

SearchFn = Callable[[Claim, list[str], int], RankedEvidence]


def make_search_fn(settings: Settings, budget: RunBudget | None = None) -> SearchFn:
    """Return search_fn(claim, queries, round_no) -> RankedEvidence using the sources in settings.sources."""
    raise NotImplementedError
