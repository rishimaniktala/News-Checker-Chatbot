from app.retrievers.dedupe import count_independent
from app.schemas import EvidenceItem, FactCheckReview, RankedEvidence


def ev(i, url, title, passage="Some distinct text %s about a thing."):
    return EvidenceItem(id=f"E{i}", source_name="x", url=url, title=title, passage=passage.replace("%s", str(i)), rerank_score=0.5)


def ranked(*items, factchecks=()):
    return RankedEvidence(claim_id="c", guardian=list(items), factchecks=list(factchecks))


def test_bbc_domains_are_one_outlet():
    assert count_independent(ranked(ev(1, "https://www.bbc.co.uk/a", "One story"),
                                    ev(2, "https://www.bbc.com/b", "Other piece"))) == 1


def test_wire_story_syndicated_to_two_outlets_counts_once():
    wire = "LONDON (Reuters) - Rates were held on Thursday."
    out = ranked(ev(1, "https://www.npr.org/a", "A", wire), ev(2, "https://www.dw.com/b", "B", wire + " More."))
    assert count_independent(out) == 1


def test_near_identical_titles_across_domains_collapse():
    out = ranked(ev(1, "https://www.npr.org/a", "Bank of England holds rates at 5.25 percent"),
                 ev(2, "https://www.dw.com/b", "Bank of England holds rates at 5.25 percent"))
    assert count_independent(out) == 1


def test_two_distinct_outlets_count_two():
    out = ranked(ev(1, "https://www.npr.org/a", "Palace refit begins"), ev(2, "https://www.dw.com/b", "Swedish NATO vote"))
    assert count_independent(out) == 2


def test_factcheck_publishers_are_counted_and_ids_filter():
    fc = FactCheckReview(id="F1", publisher="Snopes", url="https://www.snopes.com/x", claim_reviewed="c",
                         raw_rating="False", match_score=0.8)
    out = ranked(ev(1, "https://www.npr.org/a", "A story"), factchecks=[fc])
    assert count_independent(out) == 2
    assert count_independent(out, {"F1"}) == 1
    assert count_independent(out, set()) == 0
