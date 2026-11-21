"""Per-domain politeness: at most one request per domain every `min_interval` seconds."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class DomainRateLimiter:
    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._next_slot: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_interval(self, domain: str, seconds: float) -> None:
        """Slow a domain down, for example to honor a robots.txt Crawl-delay. Never speeds it up."""
        self._intervals[domain] = max(seconds, self.interval_for(domain))

    def interval_for(self, domain: str) -> float:
        return self._intervals.get(domain, self.min_interval)

    async def wait(self, domain: str) -> float:
        """Block until this domain may be hit again. Returns the seconds spent waiting."""
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = self.clock()
            slot = self._next_slot.get(domain, now)
            delay = max(0.0, slot - now)
            if delay:
                await self.sleep(delay)
            self._next_slot[domain] = max(now, slot) + self.interval_for(domain)
            return delay
