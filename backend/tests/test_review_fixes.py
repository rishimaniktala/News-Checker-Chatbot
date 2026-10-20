"""Regression tests for the reviewer's must-fix findings (R1-R7)."""

import app.llm as llm
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import agents, main
from app.budget import RunBudget
from app.retrievers.rerank import rank_factchecks
from app.rules import check_rationale
from app.schemas import Citation, ClaimVerdict, EvidenceItem, RankedEvidence, Stance, VerdictLabel


def _evidence(published=None):
    return RankedEvidence(claim_id="c1", guardian=[EvidenceItem(
        id="E1", url="https://www.theguardian.com/a", title="Jobs", rerank_score=0.9,
        passage="Unemployment stood at 4.2% last month.", published_at=published)])


def _verdict(reasoning):
    return ClaimVerdict(claim_id="c1", label=VerdictLabel.FALSE, confidence=0.8, answer="No.", reasoning=reasoning,
                        citations=[Citation(evidence_id="E1", quote="4.2%", stance=Stance.REFUTES)])


def test_r1_refutation_may_name_the_number_from_the_claim():
    v = _verdict("The claim says 9%, but unemployment stood at 4.2%.")
    assert check_rationale(v, _evidence()) != []
    assert check_rationale(v, _evidence(), claim_text="Unemployment hit 9%") == []


def test_r1_publication_year_is_allowed():
    v = _verdict("A report from 2019 gives 4.2%.")
    assert check_rationale(v, _evidence(published=datetime(2019, 5, 1))) == []


def test_r2_long_factcheck_containing_every_claim_word_does_not_score_high():
    review = {"publisher": "P", "url": "https://x/y", "raw_rating": "False",
              "claim_reviewed": "Claim that Biden won the 2020 election because of rigged voting machines and mail fraud"}
    [fc] = rank_factchecks("Biden won the 2020 election", [review])
    assert fc.match_score < 0.75


def test_r3_thinking_tokens_are_billed_as_output():
    usage = SimpleNamespace(candidates_token_count=100, thoughts_token_count=400)
    assert llm._billed_output_tokens(usage) == 500
    assert llm._billed_output_tokens(SimpleNamespace(candidates_token_count=None)) == 0


def test_r4_thinking_config_follows_the_model():
    assert llm._thinking_config("gemini-2.5-flash").thinking_budget == 512


def test_r5_bad_settings_still_end_the_stream(monkeypatch):
    monkeypatch.setenv("MAX_ITERATIONS", "abc")
    resp = TestClient(main.app).post("/api/check", json={"kind": "text", "text": "hello"})
    types_ = [line for line in resp.text.split("\n\n") if line.startswith("data: ")]
    assert '"type": "error"' in types_[-2] and '"type": "done"' in types_[-1]


def test_r6_second_claim_may_reuse_a_query():
    b = RunBudget(1, 3)
    assert b.register_query("same query", "c1")
    assert b.register_query("same query", "c2")
    assert not b.register_query("Same query!", "c1")


def test_r7_run_deadline_exhausts_the_budget():
    b = RunBudget(1, 3, max_seconds=0.0)
    assert b.exhausted


def test_health_reports_which_keys_exist_without_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-VALUE")
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
    body = TestClient(main.app).get("/health").json()
    assert body["keys_configured"]["gemini"] is True and body["keys_configured"]["guardian"] is False
    assert "SECRET-VALUE" not in str(body)


def test_embedding_failure_falls_back_to_word_overlap():
    from app.retrievers.rerank import score

    def boom(texts):
        raise RuntimeError("embedding service down")

    assert score("bank rates held", ["the bank held rates", "cats"], embed_fn=boom)[0] > 0


def test_match_score_shown_to_the_model_may_be_quoted():
    from app.schemas import FactCheckReview

    ev = _evidence()
    ev.factchecks = [FactCheckReview(id="F1", publisher="P", url="https://x/y", claim_reviewed="c",
                                     raw_rating="False", match_score=0.45)]
    assert check_rationale(_verdict("The fact-check matched with score 0.45 and 4.2% was the rate."), ev) == []


def test_quote_may_copy_the_prompt_line_with_its_label():
    from app.rules import validate_verdict
    from app.schemas import FactCheckReview

    ev = _evidence()
    ev.factchecks = [FactCheckReview(id="F1", publisher="P", url="https://x/y", claim_reviewed="Moon wall claim",
                                     raw_rating="False", match_score=0.9)]
    for eid, quote in (("F1", "claim reviewed: Moon wall claim"), ("F1", "rating: False"), ("E1", "Jobs")):
        v = _verdict("r")
        v.citations = [Citation(evidence_id=eid, quote=quote, stance=Stance.REFUTES)]
        assert validate_verdict(v, ev, 1).passed, quote


def test_fact_check_the_evidence_check_did_not_mark_relevant_never_reaches_the_verdict(monkeypatch):
    from app import orchestrator
    from app.agents import EvidenceCheck, EvidenceDecision
    from app.schemas import FactCheckReview
    from test_orchestrator import SETTINGS, good_verdict, make_budget, make_claim, search

    def search_with_unrelated_factcheck(claim, queries, n):
        ev = search(claim, queries, n)
        ev.factchecks = [FactCheckReview(id="F1", publisher="P", url="https://x/y", claim_reviewed="Musk bought Google",
                                         raw_rating="False", match_score=0.9)]
        return ev

    seen = []
    monkeypatch.setattr(orchestrator, "check_evidence", lambda c, ev, tried: EvidenceCheck(
        claim_id=c.id, decision=EvidenceDecision.SUFFICIENT, relevant_ids=["E1"], reason="ok"))
    monkeypatch.setattr(orchestrator, "give_verdict",
                        lambda c, ev, previous_failure=None: seen.append(list(ev.factchecks)) or good_verdict(c))
    report = orchestrator.check_claim(make_claim(), search_with_unrelated_factcheck, SETTINGS, make_budget(),
                                      lambda e: None, "r1")
    assert seen == [[]]
    assert report.consensus.factcheck_label is None


def test_extraction_asks_again_when_a_claim_has_newlines_in_a_word(monkeypatch):
    from app import agents
    from app.schemas import Claim, ClaimExtraction, InputType, NormalizedInput

    def reply(text):
        return ClaimExtraction(claims=[Claim(id="c1", text=text, checkworthy=True, search_queries=["q"])])

    answers = iter([reply("Prime Minister S\n\n\nbastien Lecornu resigned"), reply("Prime Minister Sébastien Lecornu resigned")])
    monkeypatch.setattr(agents, "_call", lambda *a, **k: next(answers))
    out = agents.extract_claims(NormalizedInput(input_type=InputType.TEXT, text="x"))
    assert out.claims[0].text == "Prime Minister Sébastien Lecornu resigned"


def test_todays_day_and_month_may_be_quoted():
    from datetime import date

    today = date.today()
    assert check_rationale(_verdict(f"As of {today.day} {today.month} the rate was 4.2%."), _evidence()) == []


def test_opinion_only_input_explains_why_nothing_was_checked(monkeypatch):
    from app import orchestrator
    from app.schemas import Claim, ClaimExtraction, InputType, NormalizedInput
    from test_orchestrator import SETTINGS, make_budget

    opinion = Claim(id="c1", text="X is a dictator", checkworthy=False, skip_reason="opinion")
    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[opinion]))
    report = orchestrator.check_input(NormalizedInput(input_type=InputType.TEXT, text="x"), None, SETTINGS,
                                      make_budget(), lambda e: None, "r1")
    assert report.claims == [] and "opinion" in report.answer and "can't be shown true or false" in report.answer


def test_pasted_article_url_year_narrows_the_search(monkeypatch):
    from app import orchestrator
    from app.schemas import Claim, ClaimExtraction, InputType, NormalizedInput
    from test_orchestrator import SETTINGS, make_budget

    monkeypatch.setattr(orchestrator, "extract_claims", lambda inp: ClaimExtraction(claims=[]))

    def fake_search(claim, queries, n):
        raise AssertionError("no claims, never called")

    fake_search.year_hint = None
    inp = NormalizedInput(input_type=InputType.URL, text="t", source_url="https://www.theguardian.com/world/2024/mar/07/x")
    orchestrator.check_input(inp, fake_search, SETTINGS, make_budget(), lambda e: None, "r1")
    assert fake_search.year_hint == "2024"


def test_a_loosely_matching_fact_check_does_not_override_the_verdict():
    from app.rules import compute_consensus
    from app.schemas import FactCheckReview

    ev = _evidence()
    ev.factchecks = [FactCheckReview(id="F1", publisher="P", url="https://x/y", claim_reviewed="a video of an army",
                                     raw_rating="misleading", match_score=0.77, normalized_label=VerdictLabel.MISLEADING)]
    verdict = _verdict("r")
    verdict.label, verdict.citations[0].stance = VerdictLabel.TRUE, Stance.SUPPORTS
    result = compute_consensus(verdict, ev)
    assert result.final_label == VerdictLabel.TRUE and not result.conflict


def test_missing_fact_check_publisher_falls_back_to_the_site_name():
    import httpx
    from app.retrievers import factcheck

    payload = {"claims": [{"text": "c", "claimReview": [{"url": "https://www.misbar.com/en/x", "textualRating": "False"}]}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    import os
    os.environ["FACTCHECK_API_KEY"] = "k"
    try:
        [item] = factcheck.search("q", [], client)
    finally:
        del os.environ["FACTCHECK_API_KEY"]
    assert item["publisher"] == "misbar.com"
