import asyncio

from research_agent.fetch.ratelimit import DomainRateLimiter


class FakeTime:
    """A clock that only moves when someone sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def limiter(interval=1.0):
    t = FakeTime()
    return DomainRateLimiter(interval, clock=t.clock, sleep=t.sleep), t


def test_same_domain_waits_for_interval():
    rl, t = limiter(2.0)

    async def go():
        for _ in range(3):
            await rl.wait("a.test")

    asyncio.run(go())
    assert t.sleeps == [2.0, 2.0]
    assert t.now == 4.0


def test_different_domains_do_not_block_each_other():
    rl, t = limiter(2.0)

    async def go():
        await rl.wait("a.test")
        await rl.wait("b.test")
        await rl.wait("c.test")

    asyncio.run(go())
    assert t.sleeps == []


def test_elapsed_time_counts_toward_interval():
    rl, t = limiter(2.0)

    async def go():
        await rl.wait("a.test")
        t.now += 1.5
        return await rl.wait("a.test")

    assert asyncio.run(go()) == 0.5


def test_concurrent_requests_are_serialized():
    rl, t = limiter(1.0)

    async def go():
        await asyncio.gather(*(rl.wait("a.test") for _ in range(4)))

    asyncio.run(go())
    assert t.sleeps == [1.0, 1.0, 1.0]


def test_crawl_delay_only_slows_down():
    rl, _ = limiter(1.0)
    rl.set_interval("a.test", 5.0)
    assert rl.interval_for("a.test") == 5.0
    rl.set_interval("a.test", 0.1)
    assert rl.interval_for("a.test") == 5.0
    assert rl.interval_for("b.test") == 1.0
