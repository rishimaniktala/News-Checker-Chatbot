"""Secondary source: Firecrawl web search, limited to a list of reputable outlets.

Used as a fallback when The Guardian alone does not settle a claim. Results from any
other domain are dropped, so the model never quotes a forum, a video page or a blog.
"""

import os
from urllib.parse import urlsplit

import httpx

from ..resilience import CircuitOpen, call_with_retry, raise_for_status_clean
from .guardian import MAX_PASSAGES_PER_ARTICLE, split_passages

URL = "https://api.firecrawl.dev/v1/search"
TIMEOUT = 25.0
RESULTS_PER_QUERY = 6

# News agencies, public broadcasters, fact-checkers and official bodies. Override with WEB_ALLOWED_DOMAINS.
DEFAULT_ALLOWED = (
    "reuters.com,apnews.com,bbc.com,bbc.co.uk,npr.org,pbs.org,aljazeera.com,dw.com,france24.com,euronews.com,"
    "theguardian.com,washingtonpost.com,nytimes.com,theatlantic.com,economist.com,ft.com,bloomberg.com,"
    "theconversation.com,thehindu.com,indianexpress.com,hindustantimes.com,scroll.in,"
    "svt.se,sverigesradio.se,thelocal.se,yle.fi,nrk.no,"
    "snopes.com,politifact.com,factcheck.org,fullfact.org,afpfactcheck.com,misbar.com,boomlive.in,"
    "who.int,un.org,nasa.gov,europa.eu,gov.uk,usa.gov"
)


def allowed_domains() -> set[str]:
    raw = os.environ.get("WEB_ALLOWED_DOMAINS") or DEFAULT_ALLOWED
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def site_name(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def is_allowed(url: str, allowed: set[str]) -> bool:
    host = site_name(url)
    return any(host == d or host.endswith("." + d) for d in allowed)


def search(query: str, unavailable: list[str], client: httpx.Client | None = None) -> list[dict]:
    """Return [{url, title, published_at, passage, source_name}]. [] plus a note on failure."""
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        unavailable.append("web search: no API key")
        return []
    body = {"query": query, "limit": RESULTS_PER_QUERY,
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}

    def fetch():
        resp = (client or httpx).post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
        raise_for_status_clean(resp, "web search")
        return resp.json()

    try:
        data = call_with_retry(fetch, api="firecrawl_search")
    except (CircuitOpen, httpx.HTTPError, ValueError):
        unavailable.append("web search: source unavailable")
        return []
    allowed = allowed_domains()
    out = []
    for item in data.get("data") or []:
        url = item.get("url") or ""
        if not url.startswith(("http://", "https://")) or not is_allowed(url, allowed):
            continue
        meta = item.get("metadata") or {}
        published = meta.get("publishedTime") or meta.get("article:published_time") or meta.get("modifiedTime")
        title = item.get("title") or meta.get("title") or site_name(url)
        for passage in split_passages(item.get("markdown") or item.get("description") or "")[:MAX_PASSAGES_PER_ARTICLE]:
            out.append({"url": url, "title": title, "published_at": published,
                        "passage": passage, "source_name": site_name(url)})
    return out
