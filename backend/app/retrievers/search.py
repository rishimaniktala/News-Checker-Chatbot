"""Retrieval entry point: Guardian + Fact Check, deduped and reranked."""

from typing import Callable

import re

import httpx

from ..budget import RunBudget
from ..config import Settings
from ..schemas import Claim, RankedEvidence
from . import factcheck, guardian
from .rerank import EmbedFn, rank_factchecks, rank_guardian

SearchFn = Callable[[Claim, list[str], int], RankedEvidence]


def make_search_fn(
    settings: Settings,
    budget: RunBudget | None = None,  # unused: the orchestrator owns repeat-query blocking
    embed_fn: EmbedFn | None = None,
    client: httpx.Client | None = None,
) -> SearchFn:
    """Return search_fn(claim, queries, round_no) -> RankedEvidence using the sources in settings.sources.
    The function carries `.unavailable`, a list of notes about sources that failed."""
    unavailable: list[str] = []

    def note(msgs: list[str]) -> None:
        unavailable.extend(m for m in msgs if m not in unavailable)

    def search_fn(claim: Claim, queries: list[str], round_no: int) -> RankedEvidence:
        passages: dict[tuple[str, str], dict] = {}
        reviews: dict[str, dict] = {}
        year = (re.search(r"\b(?:19|20)\d{2}\b", claim.text) or [None])[0] or search_fn.year_hint
        window = (f"{year}-01-01", f"{year}-12-31") if year else None
        for query in queries:
            notes: list[str] = []
            if "guardian" in settings.sources:
                found = guardian.search(query, notes, client, window) if window else []
                if not found:
                    found = guardian.search(query, notes, client)
                for p in found:
                    passages.setdefault((p["url"], p["passage"]), p)
            if "factcheck" in settings.sources:
                for r in factcheck.search(query, notes, client):
                    reviews.setdefault(r["url"], r)
            note(notes)
        return RankedEvidence(
            claim_id=claim.id,
            guardian=rank_guardian(claim.text, list(passages.values()), embed_fn),
            factchecks=rank_factchecks(claim.text, list(reviews.values()), embed_fn),
            attempt=round_no,
        )

    search_fn.unavailable = unavailable
    search_fn.year_hint = None  # set by the orchestrator for pasted articles whose URL carries a year
    return search_fn
