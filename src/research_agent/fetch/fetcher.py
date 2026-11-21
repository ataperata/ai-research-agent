"""Polite page fetching: cache first, then robots.txt, then the rate limiter, then HTTP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from ..cache import Cache
from ..models import Document, domain_of
from .extract import extract
from .ratelimit import DomainRateLimiter
from .robots import RobotsChecker

TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


@dataclass
class FetchResult:
    url: str
    document: Document | None = None
    error: str | None = None
    from_cache: bool = False
    blocked_by_robots: bool = False

    @property
    def ok(self) -> bool:
        return self.document is not None


class Fetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        user_agent: str,
        cache: Cache | None = None,
        limiter: DomainRateLimiter | None = None,
        robots: RobotsChecker | None = None,
        max_bytes: int = 3_000_000,
        concurrency: int = 4,
    ):
        self.client = client
        self.user_agent = user_agent
        self.cache = cache or Cache()
        self.limiter = limiter or DomainRateLimiter()
        self.robots = robots or RobotsChecker(client, user_agent, self.limiter)
        self.max_bytes = max_bytes
        self.concurrency = concurrency

    async def fetch(self, url: str) -> FetchResult:
        cached = self.cache.get("pages", url)
        if cached is not None:
            return FetchResult(url, Document.from_dict(cached), from_cache=True)
        if not await self.robots.allowed(url):
            return FetchResult(url, error="blocked by robots.txt", blocked_by_robots=True)
        await self.limiter.wait(domain_of(url))
        try:
            response = await self.client.get(
                url, headers={"User-Agent": self.user_agent}, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            return FetchResult(url, error=f"request failed: {type(exc).__name__}")
        if response.status_code >= 400:
            return FetchResult(url, error=f"HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "text/html").split(";")[0].strip().lower()
        if content_type not in TEXT_TYPES:
            return FetchResult(url, error=f"unsupported content type {content_type}")
        if len(response.content) > self.max_bytes:
            return FetchResult(url, error="page too large")
        final_url = str(response.url)
        if content_type == "text/plain":
            paragraphs = [p.strip() for p in response.text.split("\n\n") if len(p.strip()) >= 25]
            document = Document(url=url, title=domain_of(final_url), paragraphs=paragraphs)
        else:
            document = extract(response.text, final_url)
            document.url = url
        document.final_url = final_url if final_url != url else None
        if not document.paragraphs:
            return FetchResult(url, error="no readable text found")
        self.cache.set("pages", url, document.to_dict())
        return FetchResult(url, document)

    async def fetch_many(self, urls: list[str]) -> list[FetchResult]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def guarded(url: str) -> FetchResult:
            async with semaphore:
                return await self.fetch(url)

        # gather keeps input order, so output is deterministic even though fetches overlap.
        return list(await asyncio.gather(*(guarded(u) for u in urls)))
