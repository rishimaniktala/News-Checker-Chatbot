"""Ten more odd inputs and odd model replies, through the real app. The 40-case battery stays in test_weird_inputs."""

import json

import pytest

from test_failure_injection import PASSAGE, QUOTE, claim_json, error_of, extraction_json, offline, sleeps, verdict_of, verify_json
from test_v2_fallback import BACKUP, PRIMARY, V2Gemini, component, fixed_search, item, judge_json, trace_messages, v2
from app import main

SIX_NUMBERS = "In 2021 the city spent 4.5 million on 120 buses, 35 stations, 18 depots and 9 routes. " * 40


def claim_of(events):
    return verdict_of(events)["claims"][0]


# 1. a very long claim with six numbers
def test_a_long_claim_with_six_numbers_gets_a_clean_verdict(v2):
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", SIX_NUMBERS[:600])))
    events = v2(gemini, body={"kind": "text", "text": SIX_NUMBERS})
    assert claim_of(events)["claim"]["text"].startswith("In 2021 the city spent")


def test_numbers_that_only_the_claim_contains_are_allowed_in_the_answer(v2):
    claim = "The city spent 4.5 million on 120 buses in 2021."
    comp = component("spent 4.5 million", "contradicted", kind="quantity")
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", claim)),
                      judge=judge_json("FALSE", [comp], QUOTE, "refutes", answer="No, not 4.5 million."))
    assert claim_of(v2(gemini, body={"kind": "text", "text": claim}))["label"] == "FALSE"


def test_a_number_the_evidence_never_mentions_is_rejected_from_the_answer(v2):
    gemini = V2Gemini(judge=judge_json("FALSE", answer="No, it was 777 times."))
    assert claim_of(v2(gemini))["label"] == "UNVERIFIABLE"


# 2. Hindi with a year
HINDI = "भारत ने 2016 में नोटबंदी की।"


def test_a_hindi_claim_with_a_year_survives_the_round_trip(v2):
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", HINDI)))
    events = v2(gemini, body={"kind": "text", "text": HINDI})
    assert claim_of(events)["claim"]["text"] == HINDI


def test_a_hindi_claim_reaches_the_model_unescaped(v2):
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", HINDI)))
    v2(gemini, body={"kind": "text", "text": HINDI})
    assert HINDI in next(p for role, p in gemini.prompts if role == "extract")


# 3. opinions only
@pytest.mark.parametrize("text", ["This is the best film ever made.", "Mondays are awful.", "Everyone should adopt a dog.",
                                  "I think the mayor is useless."])
def test_opinion_only_input_says_nothing_to_check_with_the_reason(v2, text):
    skipped = claim_json("c1", text, checkworthy=False) | {"skip_reason": "opinion"}
    report = verdict_of(v2(V2Gemini(extract=extraction_json(skipped)), body={"kind": "text", "text": text}))
    assert report["claims"] == [] and "opinion" in report["answer"] and report["overall_label"] == "UNVERIFIABLE"


# 4. prediction
def test_a_prediction_marked_uncheckable_is_explained(v2):
    text = "Bitcoin will hit a million dollars next year."
    skipped = claim_json("c1", text, checkworthy=False) | {"skip_reason": "prediction"}
    report = verdict_of(v2(V2Gemini(extract=extraction_json(skipped)), body={"kind": "text", "text": text}))
    assert "prediction" in report["answer"]


def test_a_prediction_the_model_wrongly_marks_checkable_without_evidence_is_unverifiable(v2):
    text = "Bitcoin will hit a million dollars next year."
    gemini = V2Gemini(extract=extraction_json(claim_json("c1", text)), verify=verify_json("insufficient"))
    empty = fixed_search(guardian=[])
    assert claim_of(v2(gemini, empty, body={"kind": "text", "text": text}))["label"] == "UNVERIFIABLE"


# 5. a url inside the claim
HOSTILE_URL = "https://evil.example/phish?ref=1"


def test_a_url_inside_the_claim_is_not_fetched(v2, monkeypatch):
    from app import inputs
    monkeypatch.setattr(inputs, "normalize_url", lambda *a, **k: pytest.fail("a url inside text must not be fetched"))
    text = f"See {HOSTILE_URL} which says Sweden banned cash."
    v2(V2Gemini(extract=extraction_json(claim_json("c1", text))), body={"kind": "text", "text": text})


def test_a_judge_that_links_a_page_it_never_retrieved_is_rejected(v2):
    gemini = V2Gemini(judge=judge_json("FALSE").replace('"Because."', json.dumps(f"See {HOSTILE_URL} for proof.")))
    events = v2(gemini)
    assert claim_of(events)["label"] == "UNVERIFIABLE" and HOSTILE_URL not in json.dumps(claim_of(events)["answer"])


def test_a_judge_that_links_a_retrieved_page_is_accepted(v2):
    url = "https://www.theguardian.com/world/sweden-cash"
    gemini = V2Gemini(judge=judge_json("FALSE").replace('"Because."', json.dumps(f"See {url} for details.")))
    assert claim_of(v2(gemini))["label"] == "FALSE"


# 6. empty components
def test_an_empty_components_reply_still_gets_a_verdict(v2):
    claim = claim_of(v2(V2Gemini(judge=judge_json("FALSE", components=[]))))
    assert claim["label"] == "FALSE" and claim["components"] == []


# 7. seven components (the schema allows six)
def comps(n):
    return [component(f"part {i}", "contradicted") for i in range(n)]


def test_seven_components_are_retried_and_the_valid_retry_is_used(v2):
    gemini = V2Gemini(judge=[judge_json("FALSE", comps(7)), judge_json("FALSE", comps(6))])
    claim = claim_of(v2(gemini))
    assert claim["label"] == "FALSE" and len(claim["components"]) == 6 and gemini.n("judge", PRIMARY) == 2


def test_seven_components_every_time_end_unverifiable_not_a_crash(v2):
    claim = claim_of(v2(V2Gemini(judge=judge_json("FALSE", comps(7)))))
    assert claim["label"] == "UNVERIFIABLE"


def test_seven_components_from_the_primary_move_to_the_backup(v2):
    gemini = V2Gemini(judge=[judge_json("FALSE", comps(7)), judge_json("FALSE", comps(7)), judge_json("FALSE", comps(2))])
    done = v2(gemini)[-1]
    assert gemini.n("judge", BACKUP) == 1 and done["fallback_used"] is True


# 8. unknown component status or kind
@pytest.mark.parametrize("bad", [{"status": "maybe"}, {"status": ""}, {"status": None}, {"kind": "banana"}, {"status": "SUPPORTED"}])
def test_an_unknown_component_value_is_rejected_not_trusted(v2, bad):
    reply = json.loads(judge_json("FALSE"))
    reply["components"][0].update(bad)
    gemini = V2Gemini(judge=json.dumps(reply))
    assert claim_of(v2(gemini))["label"] == "UNVERIFIABLE"


# 9. duplicate citations
def test_duplicate_citations_do_not_inflate_anything(v2):
    reply = json.loads(judge_json("FALSE"))
    reply["citations"] = reply["citations"] * 4
    claim = claim_of(v2(V2Gemini(judge=json.dumps(reply))))
    assert claim["label"] == "FALSE" and claim["independent_sources"] == 1 and claim["confidence"] <= 0.7


def test_the_same_quote_cited_by_two_ids_of_one_outlet_counts_once(v2):
    two = [item(1), item(2, passage=PASSAGE + " Again.", title="Other title")]
    reply = json.loads(judge_json("FALSE", [component(ids=("E1", "E2"))]))
    reply["citations"].append({"evidence_id": "E2", "quote": QUOTE, "stance": "refutes"})
    claim = claim_of(v2(V2Gemini(judge=json.dumps(reply)), fixed_search(two)))
    assert claim["independent_sources"] == 1


# 10. valid JSON, wrong schema
WRONG = ['{"foo": 1}', "[]", '"just a string"', "null", "42", '{"claims": "x"}', '{"claim_id": "c1"}', "{}"]


@pytest.mark.parametrize("reply", WRONG)
def test_wrong_schema_from_the_judge_is_unverifiable(v2, reply):
    assert claim_of(v2(V2Gemini(judge=reply)))["label"] == "UNVERIFIABLE"


@pytest.mark.parametrize("reply", WRONG)
def test_wrong_schema_from_extraction_is_the_friendly_error(v2, reply):
    events = v2(V2Gemini(extract=reply))
    assert error_of(events)["message"] == main.INTERNAL_MESSAGE and events[-1]["type"] == "done"


@pytest.mark.parametrize("reply", WRONG)
def test_wrong_schema_from_the_evidence_check_does_not_crash(v2, reply):
    events = v2(V2Gemini(verify=reply))
    assert events[-1]["type"] == "done" and claim_of(events)["label"] == "UNVERIFIABLE"
