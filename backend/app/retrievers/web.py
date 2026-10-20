"""Secondary source: Firecrawl web search, limited to a list of reputable outlets.

Used as a fallback when The Guardian alone does not settle a claim. Results from any
other domain are dropped, so the model never quotes a forum, a video page or a blog.
Terms: keep only short passages (MAX_PASSAGE, 600 chars) as quoted evidence with the source
link. Pages are never stored or republished.
"""

import os
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from ..resilience import CircuitOpen, call_with_retry, raise_for_status_clean
from .guardian import MAX_PASSAGES_PER_ARTICLE, split_passages

URL = "https://api.firecrawl.dev/v1/search"
TIMEOUT = 25.0
MIN_PAGE_CHARS = 200  # shorter markdown is a search snippet, not the article

# News agencies, public broadcasters, fact-checkers and official bodies. Override with WEB_ALLOWED_DOMAINS.
DEFAULT_ALLOWED = (
    "reuters.com,apnews.com,bbc.com,bbc.co.uk,npr.org,pbs.org,aljazeera.com,dw.com,france24.com,euronews.com,"
    "theguardian.com,washingtonpost.com,nytimes.com,theatlantic.com,economist.com,ft.com,bloomberg.com,"
    "theconversation.com,thehindu.com,indianexpress.com,hindustantimes.com,scroll.in,"
    "svt.se,sverigesradio.se,thelocal.se,yle.fi,nrk.no,"
    "snopes.com,politifact.com,factcheck.org,fullfact.org,afpfactcheck.com,misbar.com,boomlive.in,"
    "who.int,un.org,nasa.gov,europa.eu,gov.uk,usa.gov"
)


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def allowed_domains() -> set[str]:
    raw = os.environ.get("WEB_ALLOWED_DOMAINS") or DEFAULT_ALLOWED
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def site_name(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def _plain_url(url: str) -> bool:
    """http(s) only, with no backslash, whitespace or control characters: browsers and urlsplit disagree on those."""
    return url.startswith(("http://", "https://")) and not any(c == "\\" or c.isspace() or ord(c) < 32 for c in url)


def is_allowed(url: str, allowed: set[str]) -> bool:
    host = site_name(url)
    return any(host == d or host.endswith("." + d) for d in allowed)


def search(query: str, unavailable: list[str], client: httpx.Client | None = None) -> list[dict]:
    """Return [{url, title, published_at, passage, source_name}]. [] plus a note on failure."""
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        unavailable.append("web search: no API key")
        return []
    body = {"query": query, "limit": _env_int("WEB_MAX_RESULTS", 6),
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
    max_passages = _env_int("WEB_MAX_PASSAGES", MAX_PASSAGES_PER_ARTICLE)
    out = []
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        unavailable.append("web search: unexpected reply")
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not _plain_url(url) or not is_allowed(url, allowed):
            continue
        markdown = item.get("markdown")
        if not isinstance(markdown, str) or len(markdown) < MIN_PAGE_CHARS:
            continue
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        published = parse_time(meta.get("publishedTime") or meta.get("article:published_time") or meta.get("modifiedTime"))
        title = next((t for t in (item.get("title"), meta.get("title")) if isinstance(t, str) and t), site_name(url))
        for passage in split_passages(markdown)[:max_passages]:
            out.append({"url": url, "title": title, "published_at": published,
                        "passage": passage, "source_name": site_name(url)})
    return out
