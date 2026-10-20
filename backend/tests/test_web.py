import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.resilience import reset_breakers
from app.retrievers import web
from app.retrievers.search import make_search_fn
from app.schemas import Claim

FIX = Path(__file__).parent / "fixtures"
CLAIM = Claim(id="c1", text="King Charles is selling Buckingham Palace", checkworthy=True, search_queries=["q"])
BODY = "The king will not live at Buckingham Palace after the refit. " * 4


def firecrawl_payload():
    return {"success": True, "data": [
        {"url": "https://www.npr.org/2026/06/26/palace", "title": "King will not live at the palace", "markdown": BODY,
         "metadata": {"publishedTime": "2026-06-26T10:00:00Z"}},
        {"url": "https://www.youtube.com/watch?v=x", "title": "video", "markdown": BODY},
        {"url": "https://www.quora.com/q", "title": "forum", "markdown": BODY},
        {"url": "https://evil.example/https://bbc.com/x", "title": "spoof", "markdown": BODY},
    ]}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    reset_breakers()
    for name in ("GUARDIAN_API_KEY", "FACTCHECK_API_KEY", "FIRECRAWL_API_KEY"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setattr("app.resilience.time.sleep", lambda s: None)


def routed(guardian_empty=False):
    hosts = []

    def handler(req: httpx.Request):
        hosts.append(req.url.host)
        if "firecrawl" in req.url.host:
            return httpx.Response(200, json=firecrawl_payload())
        if "guardian" in req.url.host:
            if guardian_empty:
                return httpx.Response(200, json={"response": {"results": []}})
            return httpx.Response(200, json=json.loads((FIX / "guardian_search.json").read_text()))
        return httpx.Response(200, json={})

    return httpx.Client(transport=httpx.MockTransport(handler)), hosts


def test_only_allowlisted_domains_survive():
    c, _ = routed()
    out = web.search("q", [], c)
    assert {p["source_name"] for p in out} == {"npr.org"}
    assert out[0]["published_at"].isoformat() == "2026-06-26T10:00:00+00:00"


def test_spoofed_hostnames_are_not_allowed():
    assert not web.is_allowed("https://evil.example/https://bbc.com/x", {"bbc.com"})
    assert not web.is_allowed("https://notbbc.com/x", {"bbc.com"})
    assert web.is_allowed("https://www.bbc.co.uk/news", {"bbc.co.uk"})


def test_web_is_skipped_in_round_one_when_the_guardian_found_something():
    c, hosts = routed()
    make_search_fn(Settings("m", True, ("guardian", "web"), 3, 0.05), client=c)(CLAIM, ["q"], 1)
    assert not any("firecrawl" in h for h in hosts)


def test_web_is_used_from_round_two():
    c, hosts = routed()
    ev = make_search_fn(Settings("m", True, ("guardian", "web"), 3, 0.05), client=c)(CLAIM, ["q"], 2)
    assert any("firecrawl" in h for h in hosts)
    assert any(e.source_name == "npr.org" for e in ev.guardian)


def test_web_is_used_in_round_one_when_the_guardian_is_empty():
    c, hosts = routed(guardian_empty=True)
    ev = make_search_fn(Settings("m", True, ("guardian", "web"), 3, 0.05), client=c)(CLAIM, ["q"], 1)
    assert [e.source_name for e in ev.guardian] == ["npr.org"] * len(ev.guardian) and ev.guardian


def test_guardian_only_setting_never_calls_the_web():
    c, hosts = routed(guardian_empty=True)
    make_search_fn(Settings("m", True, ("guardian",), 3, 0.05), client=c)(CLAIM, ["q"], 3)
    assert not any("firecrawl" in h for h in hosts)


def test_web_outage_degrades_with_a_note():
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    notes: list[str] = []
    assert web.search("q", notes, c) == []
    assert notes == ["web search: source unavailable"]


def fixture_client(captured=None):
    def handler(req: httpx.Request):
        if captured is not None:
            captured.append(json.loads(req.content))
        return httpx.Response(200, json=json.loads((FIX / "firecrawl_search.json").read_text()))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fixture_drops_snippets_and_non_allowlisted():
    out = web.search("q", [], fixture_client())
    assert {p["source_name"] for p in out} == {"reuters.com", "bbc.co.uk", "npr.org"}
    assert all(len(p["passage"]) <= 600 for p in out)


def test_published_time_is_parsed_to_datetime():
    out = web.search("q", [], fixture_client())
    assert out[0]["published_at"].year == 2023 and out[0]["published_at"].month == 8


def test_web_max_env_vars(monkeypatch):
    sent = []
    monkeypatch.setenv("WEB_MAX_RESULTS", "3")
    monkeypatch.setenv("WEB_MAX_PASSAGES", "1")
    out = web.search("q", [], fixture_client(sent))
    assert sent[0]["limit"] == 3
    assert len(out) == 3


def test_syndicated_pair_counts_once_end_to_end():
    from app.retrievers.dedupe import count_independent
    claim = Claim(id="c1", text="Bank of England rates 5.25%", checkworthy=True, search_queries=["q"])
    ev = make_search_fn(Settings("m", True, ("web",), 3, 0.05), client=fixture_client())(claim, ["q"], 2)
    assert count_independent(ev) == 2


def test_stats_count_kept_items_per_source():
    c, _ = routed()
    fn = make_search_fn(Settings("m", True, ("guardian", "web"), 3, 0.05), client=c)
    assert fn.stats == {"guardian": 0, "web": 0, "factcheck": 0}
    ev = fn(CLAIM, ["q"], 2)
    assert fn.stats["guardian"] + fn.stats["web"] == len(ev.guardian)
    assert fn.stats["web"] >= 1 and fn.stats["guardian"] >= 1


def test_month_window_pads_one_month_each_side():
    from app.retrievers.search import date_window
    assert date_window("Bank of England held at 5.25% in August 2023") == ("2023-07-01", "2023-09-30")
    assert date_window("rate cut on Jan 5, 2024") == ("2023-12-01", "2024-02-29")
    assert date_window("Sweden joined NATO in 2024") == ("2024-01-01", "2024-12-31")
    assert date_window("no date here") is None
    assert date_window("no date", "2021") == ("2021-01-01", "2021-12-31")


def test_guardian_request_uses_month_window():
    seen = []

    def handler(req: httpx.Request):
        if "guardian" in req.url.host:
            seen.append(dict(req.url.params))
            return httpx.Response(200, json=json.loads((FIX / "guardian_search.json").read_text()))
        return httpx.Response(200, json={})

    claim = Claim(id="c1", text="Rates were 5.25% in August 2023", checkworthy=True, search_queries=["q"])
    make_search_fn(Settings("m", True, ("guardian",), 3, 0.05), client=httpx.Client(transport=httpx.MockTransport(handler)))(claim, ["q"], 1)
    assert (seen[0]["from-date"], seen[0]["to-date"]) == ("2023-07-01", "2023-09-30")


def test_empty_window_falls_back_to_open_search():
    seen = []

    def handler(req: httpx.Request):
        seen.append(dict(req.url.params))
        if "from-date" in req.url.params:
            return httpx.Response(200, json={"response": {"results": []}})
        return httpx.Response(200, json=json.loads((FIX / "guardian_search.json").read_text()))

    claim = Claim(id="c1", text="Rates were 5.25% in August 2023", checkworthy=True, search_queries=["q"])
    ev = make_search_fn(Settings("m", True, ("guardian",), 3, 0.05), client=httpx.Client(transport=httpx.MockTransport(handler)))(claim, ["q"], 1)
    assert "from-date" not in seen[-1] and ev.guardian
