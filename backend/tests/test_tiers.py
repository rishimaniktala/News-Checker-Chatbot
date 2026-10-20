from app.retrievers.rerank import rank_guardian
from app.retrievers.tiers import registrable_domain, tier_of


def test_registrable_domain_and_aliases():
    assert registrable_domain("https://news.bbc.co.uk/x") == "bbc.com"
    assert registrable_domain("www.bbc.com") == "bbc.com"
    assert registrable_domain("https://sub.example.org.uk/a") == "example.org.uk"


def test_tiers():
    assert tier_of("theguardian.com") == 1
    assert tier_of("www.who.int") == 1
    assert tier_of("snopes.com") == 2
    assert tier_of("thelocal.se") == 3


def passage(url, text):
    return {"url": url, "title": "t", "passage": text, "source_name": "x"}


def test_tier_bonus_breaks_ties():
    out = rank_guardian("rates held steady", [passage("https://thelocal.se/a", "rates held steady"),
                                              passage("https://www.bbc.com/a", "rates held steady")])
    assert out[0].url.startswith("https://www.bbc.com")
    assert out[0].rerank_score == out[1].rerank_score


def test_tier_bonus_never_beats_clearly_more_relevant():
    out = rank_guardian("rates held steady today", [passage("https://www.bbc.com/a", "rates held"),
                                                    passage("https://thelocal.se/a", "rates held steady today")])
    assert out[0].url.startswith("https://thelocal.se")
