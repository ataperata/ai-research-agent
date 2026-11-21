"""robots.txt checks, cached per origin, following RFC 9309 for error cases.

* 2xx: parse the rules.
* 4xx (including 401/403): no usable robots file, so crawling is allowed.
* 5xx or network failure: the site is treated as fully disallowed.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .ratelimit import DomainRateLimiter


class RobotsChecker:
    def __init__(
        self,
        client: httpx.AsyncClient,
        user_agent: str,
        limiter: DomainRateLimiter | None = None,
    ):
        self.client = client
        self.user_agent = user_agent
        self.limiter = limiter
        self._parsers: dict[str, RobotFileParser | bool] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def _load(self, origin: str) -> RobotFileParser | bool:
        host = urlsplit(origin).hostname or ""
        if self.limiter:
            await self.limiter.wait(host)
        try:
            response = await self.client.get(
                f"{origin}/robots.txt", headers={"User-Agent": self.user_agent}, follow_redirects=True
            )
        except httpx.HTTPError:
            return False
        if response.status_code >= 500:
            return False
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        delay = parser.crawl_delay(self.user_agent)
        if delay and self.limiter:
            self.limiter.set_interval(host, float(delay))
        return parser

    async def allowed(self, url: str) -> bool:
        origin = self._origin(url)
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._parsers:
                self._parsers[origin] = await self._load(origin)
        rules = self._parsers[origin]
        if isinstance(rules, bool):
            return rules
        return rules.can_fetch(self.user_agent, url)
