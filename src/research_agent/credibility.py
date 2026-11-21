"""Score how much weight a source deserves, with the reasons spelled out.

The score is a transparent sum of simple signals, not a judgment of truth. It is used to
rank evidence and to drop sources below a threshold, and every adjustment is listed in
the report so a reader can disagree with it.
"""

from __future__ import annotations

import re
from datetime import date

from .models import Credibility, Document

SENSATIONAL = re.compile(
    r"everybody knows|everyone knows|experts agree|shocking|you won'?t believe|miracle|"
    r"secret they|game[- ]changer|\bfortune\b|totally|100% guaranteed|useless|scam",
    re.I,
)
UGC_HINTS = ("blog", "forum", "reddit", "quora", "medium.com", "substack", "talk", "board")
# Reserved test TLD used by the bundled demo corpus. Stripped so .gov.test scores like .gov.
DEMO_SUFFIX = ".test"


def _effective_host(domain: str) -> str:
    return domain[: -len(DEMO_SUFFIX)] if domain.endswith(DEMO_SUFFIX) else domain


def _year(published: str | None) -> int | None:
    if not published:
        return None
    match = re.search(r"(19|20)\d{2}", published)
    return int(match.group(0)) if match else None


def score_document(document: Document, reference_year: int | None = None) -> Credibility:
    reference_year = reference_year or date.today().year
    host = _effective_host(document.domain)
    score = 0.45
    reasons: list[str] = []

    def adjust(delta: float, why: str) -> None:
        nonlocal score
        score += delta
        reasons.append(f"{'+' if delta >= 0 else '-'}{abs(delta):.2f} {why}")

    if host.endswith((".gov", ".mil")) or ".gov." in host:
        adjust(0.30, "government domain")
    elif host.endswith(".edu") or ".ac." in host:
        adjust(0.25, "academic domain")
    elif host.endswith(".int"):
        adjust(0.25, "intergovernmental domain")
    elif host.endswith(".org"):
        adjust(0.10, "nonprofit domain")
    if any(hint in host for hint in UGC_HINTS):
        adjust(-0.20, "blog or forum")

    url = document.final_url or document.url
    if url.startswith("http://"):
        adjust(-0.05, "no HTTPS")
    if document.author:
        adjust(0.05, "named author")
    year = _year(document.published)
    if year:
        age = reference_year - year
        if age > 15:
            adjust(-0.05, f"published {year}, may be dated")
        else:
            adjust(0.05, f"dated {year}")
    else:
        adjust(-0.05, "no publication date")
    if document.has_references:
        adjust(0.10, "cites its sources")
    elif document.outbound_links >= 3:
        adjust(0.05, "links to outside sources")

    text = document.text
    hits = len(SENSATIONAL.findall(text))
    shouting = text.count("!!") + len(re.findall(r"\b[A-Z]{5,}\b", text))
    if hits or shouting:
        adjust(-min(0.30, 0.10 * (hits + shouting)), "sensational or absolute language")
    if sum(len(p.split()) for p in document.paragraphs) < 80:
        adjust(-0.05, "very little text")

    score = round(max(0.0, min(1.0, score)), 2)
    label = "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
    return Credibility(score, label, tuple(reasons))
