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
BODY = "The king will not live at Buckingham Palace after the refit. " * 3


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
    assert out[0]["published_at"] == "2026-06-26T10:00:00Z"


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
