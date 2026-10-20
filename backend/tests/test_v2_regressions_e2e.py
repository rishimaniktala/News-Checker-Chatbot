"""Known-bad cases from earlier runs, replayed through the full app with fake replies."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import config, llm, main, store
from app.logging_setup import JsonFormatter
from app.retrievers.search import make_search_fn
from test_failure_injection import FAKE_KEYS, UpstreamError, claim_json, extraction_json, offline, post, sleeps, verdict_of, verify_json
from test_v2_fallback import V2Gemini, component, fixed_search, item, judge_json, review, trace_messages, v2
from test_v2_web import Net, guardian_result


def sees_factcheck():
    return json.dumps({"claim_id": "c1", "decision": "sufficient", "relevant_ids": ["E1", "F1"], "reason": "r",
                       "new_search_queries": []})


def claim_of(events):
    return verdict_of(events)["claims"][0]


@pytest.fixture
def real_search(v2, monkeypatch):
    """Run through the real search_fn against canned Guardian replies."""
    def go(net, gemini, text):
        monkeypatch.setattr(llm, "_get_client", lambda: gemini)
        monkeypatch.setattr(main, "make_search_fn",
                            lambda settings, **kw: make_search_fn(settings, client=net.client))
        return post({"kind": "text", "text": text})
    return go


# ------------------------------------------------------------------ Sweden 2024

OLD = "Sweden banned cash payments at state shops in 2019. The parliament approved the law."


def test_sweden_2024_is_searched_in_the_named_year(real_search):
    net = Net(guardian=[guardian_result(body=OLD, published="2019-05-01T00:00:00Z")])
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", "Sweden banned cash in 2024.")))
    real_search(net, gemini, "Sweden banned cash in 2024.")
    assert net.params()[0]["from-date"] == "2024-01-01" and net.params()[0]["to-date"] == "2024-12-31"


def test_sweden_2024_with_only_2019_coverage_is_not_true(v2):
    supported = component("Sweden banned cash", "supported")
    year = component("in 2024", "unknown", ids=(), kind="time")
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", "Sweden banned cash in 2024.")),
                      judge=judge_json("TRUE", [supported, year], "Sweden banned cash payments", "supports"),
                      review=judge_json("UNVERIFIABLE", [supported, year], "Sweden banned cash payments", "supports"))
    events = v2(gemini, fixed_search([item(passage=OLD, published="2019-05-01T00:00:00Z")]))
    assert claim_of(events)["label"] != "TRUE"


def test_the_judge_sees_the_publication_year_of_the_old_article(v2):
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", "Sweden banned cash in 2024.")))
    v2(gemini, fixed_search([item(passage=OLD, published="2019-05-01T00:00:00Z")]))
    judge_prompt = next(p for role, p in gemini.prompts if role == "judge")
    assert "published: 2019-05-01" in judge_prompt


# ------------------------------------------------------------------ Bank of England

BOE_CLAIM = "The Bank of England cut interest rates in August 2023."
CUT_2024 = "The Bank of England cut interest rates in August 2024, the first cut in four years."


def test_boe_august_2023_is_searched_in_a_window_around_that_month(real_search):
    net = Net(guardian=[guardian_result(body=CUT_2024, published="2024-08-01T00:00:00Z")])
    real_search(net, V2Gemini(extract=extraction_json(claim_json("c1", BOE_CLAIM))), BOE_CLAIM)
    first = net.params()[0]
    assert first["from-date"] == "2023-07-01" and first["to-date"] == "2023-09-30"


def test_boe_2024_cut_does_not_make_the_2023_claim_true(v2):
    wrong_year = component("in August 2023", "contradicted", kind="time")
    gemini = V2Gemini(
        extract=extraction_json(claim_json("c1", BOE_CLAIM)),
        judge=judge_json("TRUE", [wrong_year], "cut interest rates in August 2024", "refutes"),
        review=judge_json("FALSE", [wrong_year], "cut interest rates in August 2024", "refutes"))
    events = v2(gemini, fixed_search([item(passage=CUT_2024, published="2024-08-01T00:00:00Z")]))
    assert claim_of(events)["label"] == "FALSE"


def test_boe_unrepaired_mislabel_never_ends_as_true(v2):
    wrong_year = component("in August 2023", "contradicted", kind="time")
    bad = judge_json("TRUE", [wrong_year], "cut interest rates in August 2024", "refutes")
    events = v2(V2Gemini(extract=extraction_json(claim_json("c1", BOE_CLAIM)), judge=bad, review=bad),
                fixed_search([item(passage=CUT_2024, published="2024-08-01T00:00:00Z")]))
    assert claim_of(events)["label"] != "TRUE"


# ------------------------------------------------------------------ Musk

MUSK = extraction_json(claim_json("c1", "Elon Musk bought Twitter."))
MUSK_PASSAGE = "Elon Musk completed his purchase of Twitter in October."
MUSK_TRUE = judge_json("TRUE", [component("Musk bought Twitter", "supported")], "completed his purchase of Twitter", "supports")


def test_an_unrelated_musk_google_fact_check_does_not_flip_the_verdict(v2):
    unrelated = review(reviewed="Elon Musk is selling Google to the Saudis", rating="False", score=0.35)
    events = v2(V2Gemini(extract=MUSK, judge=MUSK_TRUE, verify=sees_factcheck()), fixed_search([item(passage=MUSK_PASSAGE)], [unrelated]))
    assert claim_of(events)["label"] == "TRUE"


def test_the_real_musk_google_pair_scores_below_the_match_threshold(v2, monkeypatch):
    net = Net(guardian=[guardian_result(body=MUSK_PASSAGE)],
              factcheck=[{"text": "Elon Musk is selling Google to the Saudis",
                          "claimReview": [{"url": "https://snopes.com/x", "textualRating": "False", "publisher": {"name": "Snopes"}}]}])
    monkeypatch.setenv("SOURCES", "guardian,factcheck")
    monkeypatch.setattr(llm, "_get_client", lambda: V2Gemini(extract=MUSK, judge=MUSK_TRUE, verify=sees_factcheck()))
    monkeypatch.setattr(main, "make_search_fn", lambda settings, **kw: make_search_fn(settings, client=net.client))
    claim = claim_of(post({"kind": "text", "text": "Elon Musk bought Twitter."}))
    scores = [f["match_score"] for f in claim["evidence"]["factchecks"]]
    assert scores and max(scores) < 0.85 and claim["label"] == "TRUE"


def test_a_matching_fact_check_does_flip_a_wrong_verdict(v2):
    same = review(reviewed="Elon Musk bought Twitter", rating="False", score=0.95)
    claim = claim_of(v2(V2Gemini(extract=MUSK, judge=MUSK_TRUE, verify=sees_factcheck()), fixed_search([item(passage=MUSK_PASSAGE)], [same])))
    assert claim["label"] == "FALSE" and claim["confidence"] <= 0.6


# ------------------------------------------------------------------ a 0.77 match about a video

def test_a_077_fact_check_about_a_video_does_not_flip_a_verdict(v2):
    video = review(reviewed="A video shows Elon Musk burning Twitter", rating="False", score=0.77)
    claim = claim_of(v2(V2Gemini(extract=MUSK, judge=MUSK_TRUE, verify=sees_factcheck()), fixed_search([item(passage=MUSK_PASSAGE)], [video])))
    assert claim["label"] == "TRUE"


def test_a_077_fact_check_does_not_lend_a_false_label_to_an_unverifiable_claim(v2):
    video = review(reviewed="A video shows Elon Musk burning Twitter", rating="False", score=0.77)
    unsure = judge_json("UNVERIFIABLE", [component("Musk bought Twitter", "unknown", ids=())], quote=None, answer="I couldn't confirm")
    claim = claim_of(v2(V2Gemini(extract=MUSK, judge=unsure, verify=sees_factcheck()), fixed_search([item(passage=MUSK_PASSAGE)], [video])))
    assert claim["label"] == "UNVERIFIABLE"


def test_a_threshold_fact_check_may_decide(v2):
    edge = review(reviewed="Elon Musk bought Twitter", rating="False", score=0.85)
    assert claim_of(v2(V2Gemini(extract=MUSK, judge=MUSK_TRUE, verify=sees_factcheck()), fixed_search([item(passage=MUSK_PASSAGE)], [edge])))["label"] == "FALSE"


# ------------------------------------------------------------------ opinions and stances

def skipped(text, why):
    return extraction_json(claim_json("c1", text, checkworthy=False) | {"skip_reason": why})


@pytest.mark.parametrize("text, why", [("Putin is a dictator.", "opinion"), ("Vaccines are scary and I will never take one.", "personal stance"),
                                       ("The next prime minister will be great.", "prediction")])
def test_opinions_get_nothing_to_check_with_the_reason(v2, text, why):
    events = v2(V2Gemini(extract=skipped(text, why)), body={"kind": "text", "text": text})
    report = verdict_of(events)
    assert report["claims"] == [] and why in report["answer"]


def test_an_opinion_costs_no_search_and_no_judge_call(v2):
    gemini = V2Gemini(extract=skipped("Putin is a dictator.", "opinion"))
    hits = []
    v2(gemini, lambda *a: hits.append(a), body={"kind": "text", "text": "Putin is a dictator."})
    assert hits == [] and gemini.n("judge") == 0 and gemini.n("verify") == 0


def test_an_opinion_answer_invites_a_checkable_claim(v2):
    answer = verdict_of(v2(V2Gemini(extract=skipped("Putin is a dictator.", "opinion"))))["answer"]
    assert "specific claim" in answer


def test_an_opinion_beside_a_fact_still_checks_the_fact(v2):
    both = extraction_json(claim_json("c1", "Sweden banned cash."), claim_json("c2", "Putin is a dictator.", checkworthy=False))
    report = verdict_of(v2(V2Gemini(extract=both)))
    assert [c["claim"]["id"] for c in report["claims"]] == ["c1"] and len(report["skipped_claims"]) == 1


def test_a_checkable_vaccine_claim_with_a_matching_fact_check_is_false(v2):
    text = "Vaccines cause autism."
    quote = "Vaccines do not cause autism"
    comp = component("vaccines cause autism", "contradicted")
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", text)), judge=judge_json("FALSE", [comp], quote, "refutes"),
                      verify=sees_factcheck())
    claim = claim_of(v2(gemini, fixed_search([item(passage="Vaccines do not cause autism, studies find.")],
                                             [review(reviewed="Vaccines cause autism", score=0.95)]), body={"kind": "text", "text": text}))
    assert claim["label"] == "FALSE" and claim["consensus"]["factcheck_label"] == "FALSE"


# ------------------------------------------------------------------ keys never leak

LEAKY = RuntimeError(f"boom https://x.test/?api-key={FAKE_KEYS[2]} {FAKE_KEYS[3]} key={FAKE_KEYS[0]} AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE12345")


def every_fake_key_in(text):
    return [k for k in (*FAKE_KEYS, "AIzaSyFAKEFAKE") if k in text]


@pytest.mark.parametrize("role", ["judge", "review", "verify", "extract"])
def test_a_key_in_an_exception_reaches_no_event_log_or_stored_run(v2, caplog, role):
    caplog.set_level(logging.DEBUG)
    gemini = V2Gemini(**{role: LEAKY})
    if role == "review":
        mixed = judge_json("TRUE", [component("a", "contradicted")], "Sweden has not banned cash", "refutes")
        gemini.handlers["judge"] = mixed
    events = v2(gemini)
    run_id = events[-1]["run_id"]
    haystack = json.dumps(events) + caplog.text + json.dumps(store.load_run(run_id))
    assert every_fake_key_in(haystack) == []


def test_the_json_log_formatter_redacts_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEYS[2])
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, f"failed with {FAKE_KEYS[2]} and key=abc123", None, None)
    line = JsonFormatter().format(record)
    assert FAKE_KEYS[2] not in line and "abc123" not in line


def test_health_reports_key_presence_but_never_values(offline):
    body = TestClient(main.app).get("/health").text
    assert every_fake_key_in(body) == []


def test_a_guardian_outage_note_does_not_carry_the_key(real_search):
    net = Net(status={"guardian": 500})
    events = real_search(net, V2Gemini(verify=verify_json("insufficient")), "Sweden banned cash.")
    assert every_fake_key_in(json.dumps(events)) == []
