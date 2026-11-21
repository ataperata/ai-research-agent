import asyncio

import httpx

from research_agent.cache import Cache
from research_agent.fetch.fetcher import Fetcher
from research_agent.fetch.ratelimit import DomainRateLimiter
from research_agent.fetch.robots import RobotsChecker

UA = "test-agent/1.0"
PAGE = (
    "<html><head><title>Heat pumps | Site</title></head><body><nav>Home About</nav>"
    "<article><p>A heat pump moves heat instead of burning fuel, which makes it efficient, quiet, "
    "and cheap to run.</p><p>Cold climate models keep working well below freezing, according to "
    "field studies.</p></article><footer>Copyright</footer></body></html>"
)


class Recorder:
    """Mock transport that serves a small fake web and logs every request."""

    def __init__(self, robots: dict[str, httpx.Response | Exception], pages: dict[str, httpx.Response]):
        self.robots = robots
        self.pages = pages
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if request.url.path == "/robots.txt":
            outcome = self.robots.get(request.url.host, httpx.Response(404))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return self.pages.get(url, httpx.Response(404))


def run(coro):
    return asyncio.run(coro)


def make(recorder, cache=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    limiter = DomainRateLimiter(0)
    robots = RobotsChecker(client, UA, limiter)
    return (
        client,
        robots,
        Fetcher(client, user_agent=UA, cache=cache or Cache(None), limiter=limiter, robots=robots),
    )


def test_disallowed_path_is_blocked_and_never_fetched():
    rec = Recorder(
        {"a.test": httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")},
        {"https://a.test/private/x": httpx.Response(200, text=PAGE)},
    )
    _, _, fetcher = make(rec)
    result = run(fetcher.fetch("https://a.test/private/x"))
    assert result.blocked_by_robots and not result.ok
    assert "https://a.test/private/x" not in rec.requests


def test_allowed_path_is_fetched_and_extracted():
    rec = Recorder(
        {"a.test": httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")},
        {"https://a.test/public": httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})},
    )
    _, _, fetcher = make(rec)
    result = run(fetcher.fetch("https://a.test/public"))
    assert result.ok
    assert result.document.title == "Heat pumps"
    assert len(result.document.paragraphs) == 2


def test_agent_specific_rules_apply():
    rules = "User-agent: test-agent\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    rec = Recorder({"a.test": httpx.Response(200, text=rules)}, {})
    _, robots, _ = make(rec)
    assert run(robots.allowed("https://a.test/anything")) is False


def test_missing_robots_allows_and_server_error_blocks():
    rec = Recorder(
        {
            "ok.test": httpx.Response(404),
            "down.test": httpx.Response(503),
            "gone.test": httpx.ConnectError("x"),
        },
        {},
    )
    _, robots, _ = make(rec)
    assert run(robots.allowed("https://ok.test/page")) is True
    assert run(robots.allowed("https://down.test/page")) is False
    assert run(robots.allowed("https://gone.test/page")) is False


def test_robots_is_fetched_once_per_host():
    rec = Recorder({"a.test": httpx.Response(200, text="User-agent: *\nAllow: /\n")}, {})
    _, robots, _ = make(rec)

    async def go():
        await asyncio.gather(*(robots.allowed(f"https://a.test/p{i}") for i in range(5)))

    run(go())
    assert rec.requests.count("https://a.test/robots.txt") == 1


def test_crawl_delay_slows_the_domain():
    rec = Recorder({"a.test": httpx.Response(200, text="User-agent: *\nCrawl-delay: 7\n")}, {})
    _, robots, _ = make(rec)
    run(robots.allowed("https://a.test/"))
    assert robots.limiter.interval_for("a.test") == 7.0


def test_second_fetch_comes_from_cache(tmp_path):
    rec = Recorder({}, {"https://a.test/page": httpx.Response(200, text=PAGE)})
    _, _, fetcher = make(rec, Cache(tmp_path))
    first = run(fetcher.fetch("https://a.test/page"))
    page_hits = rec.requests.count("https://a.test/page")
    _, _, fresh = make(rec, Cache(tmp_path))
    second = run(fresh.fetch("https://a.test/page"))
    assert first.ok and second.ok and second.from_cache
    assert rec.requests.count("https://a.test/page") == page_hits == 1
    assert second.document.paragraphs == first.document.paragraphs


def test_errors_are_reported_not_raised():
    rec = Recorder(
        {},
        {
            "https://a.test/pdf": httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            ),
            "https://a.test/empty": httpx.Response(
                200, text="<html><body><nav>menu</nav></body></html>", headers={"content-type": "text/html"}
            ),
        },
    )
    _, _, fetcher = make(rec)
    results = run(
        fetcher.fetch_many(["https://a.test/missing", "https://a.test/pdf", "https://a.test/empty"])
    )
    assert [r.error for r in results] == [
        "HTTP 404",
        "unsupported content type application/pdf",
        "no readable text found",
    ]
