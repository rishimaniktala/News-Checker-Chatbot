"""Count independent outlets behind a set of evidence."""

import re

from ..schemas import RankedEvidence
from .rerank import _tokens
from .tiers import registrable_domain

TITLE_JACCARD = 0.9
WIRE_DOMAINS = {"reuters.com": "reuters", "ap.org": "ap"}
WIRE_CREDIT = re.compile(
    r"\((Reuters|AP|AFP)\)|[-–—/]\s*(Reuters|AP|AFP)\W*$|\b(?:with|by)\s+(Reuters|AP|AFP)\b"
    r"|\bAssociated Press\b|\bAgence France-Presse\b", re.IGNORECASE | re.MULTILINE)


def _wire(domain: str, passage: str) -> str | None:
    if domain in WIRE_DOMAINS:
        return WIRE_DOMAINS[domain]
    m = WIRE_CREDIT.search(passage)
    if not m:
        return None
    name = next((g for g in m.groups() if g), m.group(0)).lower()
    return "ap" if name.startswith("associated") else "afp" if name.startswith("agence") else name


def count_independent(evidence: RankedEvidence, evidence_ids: set[str] | None = None) -> int:
    """Distinct outlets among the given evidence ids (all items if None). Items merge when they share a
    registrable domain, a wire credit, an identical passage or a near-identical title."""
    items = [(registrable_domain(e.url), e.title, " ".join(e.passage.lower().split()), _wire(registrable_domain(e.url), e.passage))
             for e in evidence.guardian if evidence_ids is None or e.id in evidence_ids]
    items += [(registrable_domain(f.url), "", "", None)
              for f in evidence.factchecks if evidence_ids is None or f.id in evidence_ids]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def same(a, b) -> bool:
        if a[0] == b[0] or (a[3] and a[3] == b[3]) or (a[2] and a[2] == b[2]):
            return True
        ta, tb = _tokens(a[1]), _tokens(b[1])
        return bool(ta and tb and len(ta & tb) / len(ta | tb) >= TITLE_JACCARD)

    for i in range(len(items)):
        for j in range(i):
            if same(items[i], items[j]):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(items))})
