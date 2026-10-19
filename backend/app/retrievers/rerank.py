"""Score passages against a claim: embeddings if supplied, else lexical overlap."""

import math
import re
from typing import Callable

from ..rules import normalize_rating
from ..schemas import EvidenceItem, FactCheckReview

EmbedFn = Callable[[list[str]], list[list[float]]]

STOPWORDS = frozenset(
    "a an and are as at be been by for from has have in is it its of on or that the this to was were will with".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", text.lower()) if t not in STOPWORDS}


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return max(0.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))


def score(claim: str, texts: list[str], embed_fn: EmbedFn | None = None, symmetric: bool = False) -> list[float]:
    """Score each text 0..1 against the claim. symmetric=True uses Jaccard so a long text that merely
    contains every claim word does not score 1.0."""
    if not texts:
        return []
    if embed_fn:
        try:
            vectors = embed_fn([claim] + texts)
            return [_cosine(vectors[0], v) for v in vectors[1:]]
        except Exception:
            pass  # embeddings are an upgrade, not a requirement: fall back to word overlap
    want = _tokens(claim)
    if not want:
        return [0.0] * len(texts)
    if symmetric:
        return [len(want & got) / len(want | got) if (got := _tokens(t)) else 0.0 for t in texts]
    return [len(want & _tokens(t)) / len(want) for t in texts]


def rank_guardian(claim: str, passages: list[dict], embed_fn: EmbedFn | None = None, k: int = 5) -> list[EvidenceItem]:
    scores = score(claim, [p["passage"] for p in passages], embed_fn)
    top = sorted(zip(scores, passages), key=lambda sp: -sp[0])[:k]
    return [
        EvidenceItem(
            id=f"E{i}",
            source_name=p.get("source_name", "The Guardian"),
            url=p["url"],
            title=p["title"],
            published_at=p.get("published_at"),
            passage=p["passage"],
            rerank_score=s,
        )
        for i, (s, p) in enumerate(top, 1)
    ]


def rank_factchecks(claim: str, reviews: list[dict], embed_fn: EmbedFn | None = None, k: int = 5) -> list[FactCheckReview]:
    scores = score(claim, [r["claim_reviewed"] for r in reviews], embed_fn, symmetric=True)
    top = sorted(zip(scores, reviews), key=lambda sr: -sr[0])[:k]
    return [
        FactCheckReview(id=f"F{i}", match_score=s, normalized_label=normalize_rating(r["raw_rating"]), **r)
        for i, (s, r) in enumerate(top, 1)
    ]
