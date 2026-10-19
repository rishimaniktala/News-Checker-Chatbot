"""Guardian Content API client. Returns short passages only, never full articles."""

import os
import re

import httpx

from ..resilience import CircuitOpen, call_with_retry, raise_for_status_clean

URL = "https://content.guardianapis.com/search"
MAX_PASSAGE = 600
MAX_PASSAGES_PER_ARTICLE = 20
TIMEOUT = 8.0


def split_passages(text: str, limit: int = MAX_PASSAGE) -> list[str]:
    """Pack paragraphs, then sentences, then words into chunks of at most `limit` chars."""
    pieces: list[str] = []
    for para in filter(None, (p.strip() for p in text.split("\n"))):
        for sent in re.split(r"(?<=[.!?])\s+", para):
            while len(sent) > limit:
                cut = sent.rfind(" ", 0, limit)
                cut = cut if cut > 0 else limit
                pieces.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if sent:
                pieces.append(sent)
    passages: list[str] = []
    for piece in pieces:
        if passages and len(passages[-1]) + 1 + len(piece) <= limit:
            passages[-1] += " " + piece
        else:
            passages.append(piece)
    return passages


def search(query: str, unavailable: list[str], client: httpx.Client | None = None) -> list[dict]:
    """Return [{url, title, published_at, passage}]. [] plus a note on failure."""
    key = os.environ.get("GUARDIAN_API_KEY")
    if not key:
        unavailable.append("guardian: no API key")
        return []
    params = {
        "q": query,
        "api-key": key,
        "show-fields": "bodyText,headline",
        "page-size": 8,
        "order-by": "relevance",
    }

    def fetch():
        resp = (client or httpx).get(URL, params=params, timeout=TIMEOUT)
        raise_for_status_clean(resp, "guardian")
        return resp.json()

    try:
        data = call_with_retry(fetch, api="guardian")
    except CircuitOpen:
        unavailable.append("guardian: source unavailable")
        return []
    except (httpx.HTTPError, ValueError):
        unavailable.append("guardian: source unavailable")
        return []
    out = []
    for item in data.get("response", {}).get("results", []):
        fields = item.get("fields") or {}
        title = fields.get("headline") or item.get("webTitle", "")
        for passage in split_passages(fields.get("bodyText", ""))[:MAX_PASSAGES_PER_ARTICLE]:
            out.append(
                {
                    "url": item["webUrl"],
                    "title": title,
                    "published_at": item.get("webPublicationDate"),
                    "passage": passage,
                }
            )
    return out
