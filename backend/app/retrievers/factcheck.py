"""Google Fact Check Tools claims:search client."""

import os

import httpx

from ..resilience import CircuitOpen, call_with_retry, raise_for_status_clean

URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
TIMEOUT = 8.0


def search(query: str, unavailable: list[str], client: httpx.Client | None = None) -> list[dict]:
    """Return [{publisher, url, claim_reviewed, raw_rating, reviewed_at}]. [] plus a note on failure."""
    key = os.environ.get("FACTCHECK_API_KEY")
    if not key:
        unavailable.append("factcheck: no API key")
        return []
    params = {"query": query, "pageSize": 8, "languageCode": "en"}
    headers = {"X-Goog-Api-Key": key}

    def fetch():
        resp = (client or httpx).get(URL, params=params, headers=headers, timeout=TIMEOUT)
        raise_for_status_clean(resp, "factcheck")
        return resp.json()

    try:
        data = call_with_retry(fetch, api="factcheck")
    except (CircuitOpen, httpx.HTTPError, ValueError):
        unavailable.append("factcheck: source unavailable")
        return []
    out = []
    for claim in data.get("claims", []):
        for review in claim.get("claimReview", []):
            if not review.get("url") or not review.get("textualRating"):
                continue
            out.append(
                {
                    "publisher": (review.get("publisher") or {}).get("name", "Unknown"),
                    "url": review["url"],
                    "claim_reviewed": claim.get("text", ""),
                    "raw_rating": review["textualRating"],
                    "reviewed_at": review.get("reviewDate"),
                }
            )
    return out
