"""Source quality tiers and the domain helpers that dedupe and rerank share."""

from urllib.parse import urlsplit

# Outlets that publish under more than one domain count as one.
ALIASES = {"bbc.co.uk": "bbc.com", "guardian.co.uk": "theguardian.com", "guardian.com": "theguardian.com",
           "apnews.com": "ap.org"}
SECOND_LEVEL = {"co", "com", "org", "gov", "ac", "net", "edu"}

TIER1 = {"theguardian.com", "reuters.com", "ap.org", "bbc.com", "npr.org", "pbs.org", "dw.com", "france24.com",
         "svt.se", "sverigesradio.se", "yle.fi", "nrk.no", "who.int", "un.org", "nasa.gov", "europa.eu",
         "gov.uk", "usa.gov"}
TIER2 = {"snopes.com", "politifact.com", "factcheck.org", "fullfact.org", "afpfactcheck.com", "misbar.com",
         "boomlive.in", "washingtonpost.com", "nytimes.com", "economist.com", "ft.com", "bloomberg.com",
         "theatlantic.com", "aljazeera.com", "euronews.com", "thehindu.com", "indianexpress.com"}
TIER_BONUS = {1: 0.03, 2: 0.015, 3: 0.0}
FACTCHECK_DOMAINS = {"snopes.com", "politifact.com", "factcheck.org", "fullfact.org", "afpfactcheck.com",
                     "misbar.com", "boomlive.in"}


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def registrable_domain(host_or_url: str) -> str:
    """eTLD+1 by a simple rule (keeps three labels under co.uk style suffixes), then the alias map."""
    host = host_of(host_or_url) if "/" in host_or_url else host_or_url.lower().removeprefix("www.")
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
        host = ".".join(labels[-3:])
    elif len(labels) >= 2:
        host = ".".join(labels[-2:])
    return ALIASES.get(host, host)


def tier_of(domain: str) -> int:
    d = registrable_domain(domain)
    return 1 if d in TIER1 else 2 if d in TIER2 else 3


def tier_bonus(url: str) -> float:
    return TIER_BONUS[tier_of(url)]
