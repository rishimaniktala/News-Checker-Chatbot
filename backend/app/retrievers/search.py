"""Retrieval entry point: Guardian first, reputable web search as a fallback, then Fact Check. Deduped and reranked."""

from typing import Callable

import calendar
import re
from datetime import date, timedelta

import httpx

from ..budget import RunBudget
from ..config import Settings
from ..schemas import Claim, RankedEvidence
from . import factcheck, guardian, web
from .rerank import EmbedFn, rank_factchecks, rank_guardian

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTH_YEAR = re.compile(r"\b(" + "|".join(MONTHS) + r")\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?((?:19|20)\d{2})\b", re.I)


# A year only when it reads like one: after a preposition or "year", or in brackets. "2000 soldiers" is a count.
YEAR_IN_CONTEXT = re.compile(
    r"(?:\b(?:in|since|during|by|from|until|till|before|after|year|early|late|mid)\s+|\()((?:19|20)\d{2})\b(?!\s*(?:people|men|women|soldiers|troops|jobs|workers|deaths|cases|km|kg|dollars|euros|pounds|kronor))",
    re.IGNORECASE,
)


def date_window(text: str, year_hint: str | None = None) -> tuple[str, str] | None:
    """Guardian date range: the named month padded by one month each side, else the named year."""
    m = MONTH_YEAR.search(text)
    if m:
        month, year = MONTHS[m.group(1).lower()], int(m.group(2))
        first = date(year + (month - 2) // 12, (month - 2) % 12 + 1, 1)
        after = date(year + (month + 1) // 12, (month + 1) % 12 + 1, 1)
        start, end = first, after - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    year = (YEAR_IN_CONTEXT.search(text) or [None, None])[1] or year_hint
    return (f"{year}-01-01", f"{year}-12-31") if year else None


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
        window = date_window(claim.text, search_fn.year_hint)
        for query in queries:
            notes: list[str] = []
            if "guardian" in settings.sources:
                found = guardian.search(query, notes, client, window) if window else []
                if not found:
                    found = guardian.search(query, notes, client)
                for p in found:
                    passages.setdefault((p["url"], p["passage"]), p)
            # The web is the fallback: only after a round that did not settle the claim, or when the Guardian found nothing.
            if "web" in settings.sources and (round_no >= 2 or not passages):
                for p in web.search(query, notes, client):
                    passages.setdefault((p["url"], p["passage"]), p)
            if "factcheck" in settings.sources:
                for r in factcheck.search(query, notes, client):
                    reviews.setdefault(r["url"], r)
            note(notes)
        ranked = RankedEvidence(
            claim_id=claim.id,
            guardian=rank_guardian(claim.text, list(passages.values()), embed_fn),
            factchecks=rank_factchecks(claim.text, list(reviews.values()), embed_fn),
            attempt=round_no,
        )
        guardian_kept = sum(e.source_name == "The Guardian" for e in ranked.guardian)
        search_fn.stats.update(guardian=guardian_kept, web=len(ranked.guardian) - guardian_kept,
                               factcheck=len(ranked.factchecks))
        return ranked

    search_fn.unavailable = unavailable
    search_fn.stats = {"guardian": 0, "web": 0, "factcheck": 0}
    search_fn.year_hint = None  # set by the orchestrator for pasted articles whose URL carries a year
    return search_fn
