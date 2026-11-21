import asyncio

import pytest

from research_agent.models import Plan, SearchResult, SubQuery
from research_agent.pipeline import ResearchAgent, Settings
from research_agent.search.providers import SearchError


class SlowSearch:
    name = "slow"

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.in_flight = 0
        self.peak = 0

    async def search(self, query, max_results=5):
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        # Later queries finish first, so ordering cannot come from completion time.
        await asyncio.sleep(0.05 if query == "a" else 0.01)
        self.in_flight -= 1
        if query in self.fail:
            raise SearchError("quota")
        return [
            SearchResult(f"https://{query}.test/{i}", query, "", self.name, i + 1)
            for i in range(max_results)
        ]


def plan(*queries):
    return Plan("q?", "what", "q", tuple(SubQuery(f"facet-{q}", q) for q in queries))


def test_sub_queries_run_together_and_merge_in_plan_order():
    search = SlowSearch(fail={"b"})
    logs = []
    agent = ResearchAgent(search, fetcher=None, settings=Settings(results_per_query=2), log=logs.append)
    hits = asyncio.run(agent._gather_results(plan("a", "b", "c")))
    assert search.peak == 3
    assert [hit.url for hit, _ in hits] == [
        "https://a.test/0",
        "https://c.test/0",
        "https://a.test/1",
        "https://c.test/1",
    ]
    assert logs == [
        "search [facet-a] 'a': 2 results",
        "search failed for 'b': quota",
        "search [facet-c] 'c': 2 results",
    ]


def test_every_search_failing_is_an_error():
    agent = ResearchAgent(SlowSearch(fail={"a", "b"}), fetcher=None)
    with pytest.raises(SearchError, match="every search query failed"):
        asyncio.run(agent._gather_results(plan("a", "b")))
