"""Report cache end to end through the real app, counting model calls."""

import base64
import json

import pytest

from app import inputs, main, prompts, store
from app.schemas import InputType, NormalizedInput
from test_failure_injection import claim_json, extraction_json, offline, post, sleeps, verdict_of
from test_v2_fallback import PRIMARY, UpstreamError, V2Gemini, fixed_search, judge_json, trace_messages, v2

TEXT = "Sweden banned cash."
BODY = {"kind": "text", "text": TEXT}
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()


@pytest.fixture
def cached(v2, monkeypatch):
    """Like v2 but with a 24 hour cache. go(gemini, search_fn=None, body=None) -> events."""
    monkeypatch.setenv("CACHE_TTL_HOURS", "24")
    return v2


def total(gemini):
    return len(gemini.calls)


def test_identical_text_twice_is_served_from_cache(cached):
    gemini = V2Gemini()
    cached(gemini)
    second = cached(gemini)
    assert second[-1]["cached"] is True


def test_a_cache_hit_makes_no_model_call(cached):
    gemini = V2Gemini()
    cached(gemini)
    before = total(gemini)
    cached(gemini)
    assert total(gemini) == before


def test_a_cache_hit_costs_nothing(cached):
    gemini = V2Gemini()
    cached(gemini)
    done = cached(gemini)[-1]
    assert done["cost_usd"] == 0 and done["tokens_in"] == 0 and done["tokens_out"] == 0


def test_a_cache_hit_says_so_in_the_trace(cached):
    gemini = V2Gemini()
    cached(gemini)
    assert "Served from cache" in trace_messages(cached(gemini))


def test_a_cache_hit_replays_the_same_answer_under_a_new_run_id(cached):
    gemini = V2Gemini()
    first, second = cached(gemini), cached(gemini)
    a, b = verdict_of(first), verdict_of(second)
    assert b["run_id"] != a["run_id"] and b["claims"][0]["answer"] == a["claims"][0]["answer"]
    assert b["run_id"] == second[-1]["run_id"]


def test_the_first_run_is_not_marked_cached(cached):
    assert cached(V2Gemini())[-1]["cached"] is False


def test_a_cache_hit_is_stored_as_its_own_run(cached):
    gemini = V2Gemini()
    cached(gemini)
    run_id = cached(gemini)[-1]["run_id"]
    assert store.load_run(run_id)["events"][-1]["cached"] is True


def test_spacing_still_hits(cached):
    gemini = V2Gemini()
    cached(gemini)
    again = cached(gemini, body={"kind": "text", "text": "  Sweden   banned  cash. "})
    assert again[-1]["cached"] is True


def test_a_different_text_misses(cached):
    gemini = V2Gemini()
    cached(gemini)
    assert cached(gemini, body={"kind": "text", "text": "Sweden banned notes."})[-1]["cached"] is False


def test_a_hit_still_works_when_every_model_is_down(cached):
    gemini = V2Gemini()
    cached(gemini)
    down = V2Gemini(extract=UpstreamError(503), judge=UpstreamError(503), verify=UpstreamError(503))
    assert cached(down)[-1]["cached"] is True and total(down) == 0


# ------------------------------------------------------------------ not cached

def test_a_run_with_a_source_problem_is_not_cached(cached):
    gemini = V2Gemini()
    search = fixed_search(notes=["guardian: source unavailable"])
    cached(gemini, search)
    before = total(gemini)
    second = cached(gemini, search)
    assert second[-1]["cached"] is False and total(gemini) > before


def test_a_run_with_a_failed_claim_is_not_cached(cached):
    gemini = V2Gemini(judge=RuntimeError("kaboom"))
    cached(gemini)
    before = total(gemini)
    cached(gemini)
    assert total(gemini) > before


def test_a_run_that_ended_in_an_error_is_not_cached(cached):
    gemini = V2Gemini(extract="<html>")
    cached(gemini)
    before = total(gemini)
    cached(gemini)
    assert total(gemini) > before


def test_a_problem_run_does_not_poison_the_next_good_run(cached):
    cached(V2Gemini(judge=RuntimeError("kaboom")))
    good = V2Gemini()
    second = cached(good)
    assert second[-1]["cached"] is False and verdict_of(second)["claims"][0]["label"] == "FALSE"


def test_url_requests_are_never_cached(cached, monkeypatch):
    page = NormalizedInput(input_type=InputType.URL, text=TEXT, source_url="https://www.theguardian.com/a")
    monkeypatch.setattr(inputs, "normalize_url", lambda url, **kw: page)
    gemini = V2Gemini()
    body = {"kind": "url", "url": "https://www.theguardian.com/a"}
    cached(gemini, body=body)
    before = total(gemini)
    second = cached(gemini, body=body)
    assert second[-1]["cached"] is False and total(gemini) > before


def test_image_requests_are_never_cached(cached):
    ocr = json.dumps({"text": TEXT, "context_note": "screenshot", "is_legible": True})
    gemini = V2Gemini(ocr=ocr)
    body = {"kind": "image", "image_b64": PNG, "mime": "image/png"}
    cached(gemini, body=body)
    before = total(gemini)
    second = cached(gemini, body=body)
    assert second[-1]["cached"] is False and total(gemini) > before


def test_a_text_run_does_not_serve_a_later_url_run_with_the_same_text(cached, monkeypatch):
    page = NormalizedInput(input_type=InputType.URL, text=TEXT, source_url="https://www.theguardian.com/a")
    monkeypatch.setattr(inputs, "normalize_url", lambda url, **kw: page)
    gemini = V2Gemini()
    cached(gemini)
    assert cached(gemini, body={"kind": "url", "url": "https://www.theguardian.com/a"})[-1]["cached"] is False


# ------------------------------------------------------------------ misses on config and time

def test_a_different_prompt_version_misses(cached, monkeypatch):
    gemini = V2Gemini()
    cached(gemini)
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "v-next")
    assert cached(gemini)[-1]["cached"] is False


def test_a_different_primary_model_misses(cached, monkeypatch):
    gemini = V2Gemini()
    cached(gemini)
    monkeypatch.setenv("MODEL_PRIMARY", "gemini-3.5-flash")
    assert cached(gemini)[-1]["cached"] is False


def test_a_different_source_list_misses(cached, monkeypatch):
    gemini = V2Gemini()
    cached(gemini)
    monkeypatch.setenv("SOURCES", "guardian")
    assert cached(gemini)[-1]["cached"] is False


def age_cache(hours):
    with store._connect() as db:
        db.execute("UPDATE report_cache SET created = datetime('now', ?)", (f"-{hours} hours",))


def test_an_entry_older_than_the_ttl_misses(cached):
    gemini = V2Gemini()
    cached(gemini)
    age_cache(25)
    assert cached(gemini)[-1]["cached"] is False


def test_an_entry_inside_the_ttl_still_hits(cached):
    gemini = V2Gemini()
    cached(gemini)
    age_cache(23)
    assert cached(gemini)[-1]["cached"] is True


def test_a_miss_after_expiry_refreshes_the_entry(cached):
    gemini = V2Gemini()
    cached(gemini)
    age_cache(25)
    cached(gemini)
    assert cached(gemini)[-1]["cached"] is True


def test_a_zero_ttl_disables_the_cache(cached, monkeypatch):
    monkeypatch.setenv("CACHE_TTL_HOURS", "0")
    gemini = V2Gemini()
    cached(gemini)
    assert cached(gemini)[-1]["cached"] is False


def test_a_broken_cache_table_does_not_break_a_run(cached, monkeypatch):
    from app import cache
    monkeypatch.setattr(cache, "get", lambda text: (_ for _ in ()).throw(RuntimeError("db locked")))
    assert verdict_of(cached(V2Gemini()))["claims"][0]["label"] == "FALSE"
