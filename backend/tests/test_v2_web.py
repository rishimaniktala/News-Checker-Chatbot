"""Web search fallback: allowlist spoofing, dropped hosts, Firecrawl failures, when the web is used."""

import json
from collections import Counter

import httpx
import pytest

from app import llm, main, resilience
from app.config import load_settings
from app.retrievers import web
from app.retrievers.search import make_search_fn
from test_failure_injection import FAKE_KEYS, PASSAGE, claim_json, extraction_json, offline, post, sleeps, verdict_of, verify_json
from test_v2_fallback import V2Gemini, judge_json, trace_messages

ARTICLE = "Sweden has not banned cash. Shops may refuse cash. " * 6
LONG = ARTICLE + "More reporting follows here."


def guardian_result(url="https://www.theguardian.com/world/sweden-cash", published="2024-03-12T14:05:00Z", body=PASSAGE):
    return {"webUrl": url, "webTitle": "Sweden and cash", "webPublicationDate": published,
            "fields": {"headline": "Sweden and cash", "bodyText": body}}


def web_item(url, markdown=LONG, title="t"):
    return {"url": url, "title": title, "markdown": markdown, "metadata": {"publishedTime": "2024-03-01T00:00:00Z"}}


class Net:
    """Guardian, Fact Check and Firecrawl over httpx.MockTransport. Records every request."""

    def __init__(self, guardian=(), firecrawl=(), status=None, factcheck=()):
        self.guardian, self.firecrawl, self.factcheck = list(guardian), list(firecrawl), list(factcheck)
        self.status = {"guardian": 200, "factcheck": 200, "firecrawl": 200, **(status or {})}
        self.hits: Counter = Counter()
        self.requests: list[httpx.Request] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, req):
        name = "guardian" if "guardian" in req.url.host else "factcheck" if "factcheck" in req.url.host else "firecrawl"
        self.hits[name] += 1
        self.requests.append(req)
        if self.status[name] != 200:
            return httpx.Response(self.status[name])
        body = {"guardian": {"response": {"results": self.guardian}}, "factcheck": {"claims": self.factcheck},
                "firecrawl": {"data": self.firecrawl}}[name]
        return httpx.Response(200, json=body)

    def params(self, name="guardian"):
        return [dict(r.url.params) for r in self.requests if name in r.url.host]


@pytest.fixture
def web_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", FAKE_KEYS[3])
    monkeypatch.delenv("WEB_ALLOWED_DOMAINS", raising=False)
    resilience.reset_breakers()
    yield
    resilience.reset_breakers()


# ------------------------------------------------------------------ allowlist spoofing

SPOOFS = [
    "https://evil.example/https://bbc.com/news",
    "https://bbc.com.evil.example/news",
    "https://evilbbc.com/news",
    "https://notbbc.com/news",
    "https://bbc.com@evil.example/news",
    "https://evil.example/?next=https://bbc.com",
    "https://evil.example/#bbc.com",
    "https://evil.example/bbc.com",
    "https://bbc.co.uk.evil.example/",
    "ftp://bbc.com/news",
    "bbc.com/news",
    "",
]


@pytest.mark.parametrize("url", SPOOFS)
def test_spoofed_urls_are_not_allowed(url):
    assert not web.is_allowed(url, web.allowed_domains()) or not url.startswith(("http://", "https://"))


@pytest.mark.parametrize("url", SPOOFS)
def test_spoofed_results_never_reach_the_evidence(web_env, url):
    net = Net(firecrawl=[web_item(url)])
    assert web.search("q", [], net.client) == []


@pytest.mark.parametrize("url", ["https://www.bbc.com/news/a", "https://news.bbc.co.uk/a", "https://BBC.COM/a",
                                 "https://www.reuters.com/world/x", "http://apnews.com/x"])
def test_real_outlets_pass_the_allowlist(web_env, url):
    assert [r["url"] for r in web.search("q", [], Net(firecrawl=[web_item(url)]).client)]


@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=1", "https://youtu.be/abc", "https://www.quora.com/q",
                                 "https://reddit.com/r/x", "https://medium.com/@a/b", "https://x.com/a/status/1"])
def test_video_and_forum_pages_are_dropped(web_env, url):
    assert web.search("q", [], Net(firecrawl=[web_item(url)]).client) == []


def test_only_the_allowed_results_of_a_mixed_reply_survive(web_env):
    net = Net(firecrawl=[web_item("https://youtube.com/w"), web_item("https://www.bbc.com/n"),
                         web_item("https://evil.example/https://bbc.com/x"), web_item("https://www.quora.com/q")])
    assert {r["source_name"] for r in web.search("q", [], net.client)} == {"bbc.com"}


def test_a_snippet_shorter_than_a_page_is_dropped(web_env):
    assert web.search("q", [], Net(firecrawl=[web_item("https://www.bbc.com/n", markdown="short")]).client) == []


def test_the_allowlist_can_be_overridden_by_env(web_env, monkeypatch):
    monkeypatch.setenv("WEB_ALLOWED_DOMAINS", "example.org")
    assert web.search("q", [], Net(firecrawl=[web_item("https://www.bbc.com/n")]).client) == []


def test_a_passage_is_cut_to_the_quote_limit(web_env):
    out = web.search("q", [], Net(firecrawl=[web_item("https://www.bbc.com/n", markdown="word " * 2000)]).client)
    assert out and max(len(p["passage"]) for p in out) <= 600


def test_a_reply_with_a_null_data_field_is_not_a_crash(web_env):
    net = Net()
    net.firecrawl = None
    assert web.search("q", [], net.client) == []


# ------------------------------------------------------------------ Firecrawl failures

@pytest.mark.parametrize("code, hits", [(402, 1), (401, 1), (429, 3), (500, 3), (503, 3)])
def test_firecrawl_errors_degrade_with_a_note(web_env, sleeps, code, hits):
    net = Net(status={"firecrawl": code})
    notes: list[str] = []
    assert web.search("q", notes, net.client) == [] and notes == ["web search: source unavailable"]
    assert net.hits["firecrawl"] == hits


def test_missing_firecrawl_key_is_noted_not_raised(monkeypatch):
    notes: list[str] = []
    assert web.search("q", notes, Net().client) == [] and notes == ["web search: no API key"]


def test_non_json_firecrawl_reply_degrades(web_env):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    notes: list[str] = []
    assert web.search("q", notes, client) == [] and notes


def test_firecrawl_circuit_opens_after_three_failed_searches(web_env, sleeps):
    net = Net(status={"firecrawl": 500})
    for _ in range(4):
        web.search("q", [], net.client)
    assert net.hits["firecrawl"] == 9


def test_the_firecrawl_key_is_sent_only_as_a_header(web_env):
    net = Net(firecrawl=[web_item("https://www.bbc.com/n")])
    web.search("q", [], net.client)
    request = net.requests[0]
    assert FAKE_KEYS[3] not in str(request.url) and FAKE_KEYS[3] not in request.content.decode()


# ------------------------------------------------------------------ through the app

@pytest.fixture
def pipeline(offline, monkeypatch, web_env):
    monkeypatch.setenv("SOURCES", "guardian,web")
    monkeypatch.setenv("CACHE_TTL_HOURS", "0")

    def go(net, gemini=None, text="Sweden banned cash."):
        gemini = gemini or V2Gemini()
        monkeypatch.setattr(llm, "_get_client", lambda: gemini)
        monkeypatch.setattr(main, "make_search_fn",
                            lambda settings, budget, **kw: make_search_fn(settings, None, client=net.client))
        return post({"kind": "text", "text": text})
    return go


def test_web_is_skipped_when_the_guardian_answers_and_the_claim_is_settled(pipeline):
    net = Net(guardian=[guardian_result()], firecrawl=[web_item("https://www.bbc.com/n")])
    pipeline(net)
    assert net.hits["firecrawl"] == 0


def test_web_runs_in_round_one_when_the_guardian_is_empty(pipeline):
    net = Net(firecrawl=[web_item("https://www.bbc.com/n", markdown=ARTICLE)])
    events = pipeline(net, V2Gemini(verify=verify_json("sufficient")))
    assert net.hits["firecrawl"] >= 1 and verdict_of(events)["claims"][0]["label"] != "UNVERIFIABLE"


def test_web_joins_from_round_two_when_the_first_round_was_not_enough(pipeline):
    net = Net(guardian=[guardian_result()], firecrawl=[web_item("https://www.bbc.com/n", markdown=ARTICLE)])
    replies = [verify_json("insufficient", ["second round words"]), verify_json("sufficient")]
    pipeline(net, V2Gemini(verify=replies))
    assert net.hits["firecrawl"] == 1


def test_web_evidence_is_labelled_with_its_outlet_in_the_report(pipeline):
    net = Net(firecrawl=[web_item("https://www.bbc.com/n", markdown=ARTICLE)])
    claim = verdict_of(pipeline(net))["claims"][0]
    assert {e["source_name"] for e in claim["evidence"]["guardian"]} == {"bbc.com"}


def test_round_stats_report_web_results(pipeline):
    net = Net(firecrawl=[web_item("https://www.bbc.com/n", markdown=ARTICLE)])
    events = pipeline(net)
    assert any("web 1" in m or "web 2" in m or "web 3" in m for m in trace_messages(events) if m.startswith("Round"))


@pytest.mark.parametrize("code", [402, 429, 500])
def test_firecrawl_failure_shows_a_web_search_note_in_the_trace(pipeline, sleeps, code):
    events = pipeline(Net(status={"firecrawl": code}))
    assert any(m.startswith("Source problem: web search") for m in trace_messages(events))


@pytest.mark.parametrize("code", [402, 429, 500])
def test_firecrawl_failure_still_ends_with_a_verdict(pipeline, sleeps, code):
    events = pipeline(Net(status={"firecrawl": code}), V2Gemini(verify=verify_json("insufficient")))
    assert verdict_of(events)["claims"][0]["label"] == "UNVERIFIABLE"


def test_firecrawl_failure_does_not_hide_a_guardian_answer(pipeline, sleeps):
    net = Net(guardian=[guardian_result()], status={"firecrawl": 500})
    replies = [verify_json("insufficient", ["second round words"]), verify_json("sufficient")]
    events = pipeline(net, V2Gemini(verify=replies))
    assert verdict_of(events)["claims"][0]["label"] == "FALSE"


def test_a_run_with_a_web_problem_is_not_cached(pipeline, sleeps, monkeypatch):
    monkeypatch.setenv("CACHE_TTL_HOURS", "24")
    net = Net(status={"firecrawl": 500})
    pipeline(net, V2Gemini(verify=verify_json("insufficient")))
    gemini = V2Gemini(verify=verify_json("insufficient"))
    events = pipeline(net, gemini)
    assert events[-1]["cached"] is False
