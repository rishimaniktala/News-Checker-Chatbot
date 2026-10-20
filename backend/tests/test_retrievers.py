import json
from pathlib import Path

import httpx
import pytest

from app.budget import RunBudget
from app.config import Settings
from app.resilience import reset_breakers
from app.retrievers.guardian import split_passages
from app.retrievers.rerank import rank_guardian
from app.retrievers.search import make_search_fn
from app.schemas import Claim, RankedEvidence

FIX = Path(__file__).parent / "fixtures"
CLAIM = Claim(id="c1", text="The Bank of England held interest rates at 5.25%", checkworthy=True,
              search_queries=["bank of england rates"])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    reset_breakers()
    monkeypatch.setenv("GUARDIAN_API_KEY", "test")
    monkeypatch.setenv("FACTCHECK_API_KEY", "test")
    monkeypatch.setattr("app.resilience.time.sleep", lambda s: None)


def settings(sources):
    return Settings("m", True, sources, 3, 0.05)


def client(guardian_status=200):
    hits = []

    def handler(req: httpx.Request):
        hits.append(req.url.host)
        if "guardian" in req.url.host:
            if guardian_status != 200:
                return httpx.Response(guardian_status)
            return httpx.Response(200, json=json.loads((FIX / "guardian_search.json").read_text()))
        return httpx.Response(200, json=json.loads((FIX / "factcheck_search.json").read_text()))

    return httpx.Client(transport=httpx.MockTransport(handler)), hits


def test_fixtures_parse_into_ranked_evidence():
    c, _ = client()
    fn = make_search_fn(settings(("guardian", "factcheck")), client=c)
    ev = fn(CLAIM, CLAIM.search_queries, 2)
    assert isinstance(ev, RankedEvidence) and ev.attempt == 2
    assert ev.guardian[0].id == "E1" and "5.25%" in ev.guardian[0].passage
    assert [f.id for f in ev.factchecks] == ["F1", "F2"]
    assert ev.factchecks[0].normalized_label is not None
    assert fn.unavailable == []


def test_guardian_503_degrades_with_note():
    c, _ = client(guardian_status=503)
    fn = make_search_fn(settings(("guardian",)), client=c)
    ev = fn(CLAIM, CLAIM.search_queries, 1)
    assert ev.is_empty and fn.unavailable == ["guardian: source unavailable"]


def test_guardian_only_never_calls_factcheck():
    c, hits = client()
    make_search_fn(settings(("guardian",)), client=c)(CLAIM, CLAIM.search_queries, 1)
    assert hits and all("guardian" in h for h in hits)


def test_passages_never_exceed_limit():
    text = ("Word " * 300) + "\n" + "Short sentence. " * 100 + "\n" + "x" * 2000
    passages = split_passages(text)
    assert passages and all(len(p) <= 600 for p in passages)


def test_rerank_orders_relevant_first_lexically():
    ps = [{"url": "u1", "title": "t", "passage": "Cats sleep for most of the day."},
          {"url": "u2", "title": "t", "passage": "The Bank of England held interest rates at 5.25%."}]
    out = rank_guardian(CLAIM.text, ps)
    assert out[0].url == "u2" and out[0].rerank_score > out[1].rerank_score


def test_rerank_with_embed_fn():
    def embed(texts):
        return [[1.0, 0.0] if "rates" in t else [0.0, 1.0] for t in texts]

    ps = [{"url": "u1", "title": "t", "passage": "Cats."}, {"url": "u2", "title": "t", "passage": "rates"}]
    assert rank_guardian(CLAIM.text, ps, embed)[0].url == "u2"


def test_year_in_claim_narrows_guardian_to_that_period():
    seen = []

    def handler(req: httpx.Request):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=json.loads((FIX / "guardian_search.json").read_text()))

    claim = CLAIM.model_copy(update={"text": "Sweden joined NATO in 2024"})
    fn = make_search_fn(settings(("guardian",)), client=httpx.Client(transport=httpx.MockTransport(handler)))
    fn(claim, ["Sweden NATO 2024"], 1)
    assert seen[0]["from-date"] == "2024-01-01" and seen[0]["to-date"] == "2024-12-31"


def test_empty_window_falls_back_to_unfiltered_search():
    seen = []

    def handler(req: httpx.Request):
        seen.append("from-date" in req.url.params)
        body = {"response": {"results": []}} if "from-date" in req.url.params else json.loads((FIX / "guardian_search.json").read_text())
        return httpx.Response(200, json=body)

    claim = CLAIM.model_copy(update={"text": "Rates held in 1999"})
    fn = make_search_fn(settings(("guardian",)), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert fn(claim, ["rates 1999"], 1).guardian
    assert seen == [True, False]
