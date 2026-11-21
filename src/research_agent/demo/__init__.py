"""Offline demo: a bundled corpus served through a mock HTTP transport.

Nothing here touches the network. The fixture search engine ranks the bundled pages with
BM25, and the pages are served to the real Fetcher by an httpx.MockTransport, so robots.txt
checks, rate limiting, caching and extraction all run exactly as they would live.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .. import USER_AGENT
from ..cache import Cache
from ..fetch.extract import extract
from ..fetch.fetcher import Fetcher
from ..fetch.ratelimit import DomainRateLimiter
from ..models import SearchResult
from ..pipeline import ResearchAgent, Settings
from ..text import BM25, content_terms

CORPUS_DIR = Path(__file__).parent / "corpus"


@dataclass
class DemoCase:
    slug: str
    question: str
    directory: Path
    documents: list[dict]
    robots: dict[str, str]
    reference_year: int

    def html_for(self, url: str) -> str | None:
        for doc in self.documents:
            if doc["url"] == url:
                return (self.directory / doc["file"]).read_text("utf-8")
        return None


def load_cases() -> list[DemoCase]:
    cases = []
    for manifest in sorted(CORPUS_DIR.glob("*/manifest.json")):
        data = json.loads(manifest.read_text("utf-8"))
        cases.append(
            DemoCase(
                slug=manifest.parent.name,
                question=data["question"],
                directory=manifest.parent,
                documents=data["documents"],
                robots=data.get("robots", {}),
                reference_year=int(data.get("reference_year", 2026)),
            )
        )
    return cases


def find_case(query: str) -> DemoCase:
    cases = load_cases()
    query = query.strip()
    if query.isdigit() and 1 <= int(query) <= len(cases):
        return cases[int(query) - 1]
    for case in cases:
        if query.lower() in (case.slug, case.question.lower()):
            return case
    wanted = set(content_terms(query))
    scored = [(len(wanted & set(content_terms(c.question))), c) for c in cases]
    best_score, best = max(scored, key=lambda pair: pair[0])
    if best_score >= 2:
        return best
    options = "; ".join(f"{i}. {c.question}" for i, c in enumerate(cases, 1))
    raise ValueError(f"no demo matches {query!r}. Available demos: {options}")


class FixtureSearch:
    """BM25 search over the demo corpus. Results look like any other provider's."""

    name = "fixture"

    def __init__(self, case: DemoCase):
        self.case = case
        self.entries = []
        for doc in case.documents:
            parsed = extract(case.html_for(doc["url"]) or "", doc["url"])
            self.entries.append((doc["url"], parsed.title, parsed.paragraphs))
        self.index = BM25([content_terms(f"{t} {t} {' '.join(p)}") for _, t, p in self.entries])

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ranked = self.index.rank(content_terms(query))
        results = []
        for i, score in ranked:
            if score <= 0 or len(results) >= max_results:
                break
            url, title, paragraphs = self.entries[i]
            snippet = paragraphs[0][:200] if paragraphs else ""
            results.append(SearchResult(url, title, snippet, self.name, len(results) + 1))
        return results


def fixture_transport(case: DemoCase) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host = urlsplit(url).hostname or ""
        if request.url.path == "/robots.txt":
            if host in case.robots:
                return httpx.Response(200, text=case.robots[host])
            return httpx.Response(404, text="not found")
        html = case.html_for(url)
        if html is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})

    return httpx.MockTransport(handler)


def build_demo_agent(case: DemoCase, log=None) -> tuple[ResearchAgent, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=fixture_transport(case))
    limiter = DomainRateLimiter(min_interval=0.01)
    fetcher = Fetcher(client, user_agent=USER_AGENT, cache=Cache(None), limiter=limiter)
    settings = Settings(reference_year=case.reference_year)
    agent = ResearchAgent(FixtureSearch(case), fetcher, settings=settings, mode="offline demo", log=log)
    return agent, client


async def run_demo(case: DemoCase, log=None):
    agent, client = build_demo_agent(case, log)
    async with client:
        return await agent.run(case.question)


__all__ = ["DemoCase", "FixtureSearch", "build_demo_agent", "find_case", "load_cases", "run_demo"]
