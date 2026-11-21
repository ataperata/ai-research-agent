import asyncio
import json

import httpx
import pytest
import respx

from research_agent.cache import Cache
from research_agent.llm.providers import AnthropicClient, OpenAIClient, llm_from_env
from research_agent.search.providers import (
    BraveSearch,
    CachedSearch,
    SearchError,
    SerpAPISearch,
    TavilySearch,
    provider_from_env,
)


def run(coro):
    return asyncio.run(coro)


@respx.mock
def test_tavily_parsing_and_auth():
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"title": "A", "url": "https://a.test", "content": "snip"},
                    {"title": "bad", "url": "ftp://x"},
                ]
            },
        )
    )

    async def go():
        async with httpx.AsyncClient() as client:
            return await TavilySearch("key", client).search("q", 3)

    results = run(go())
    assert [(r.url, r.snippet, r.provider, r.rank) for r in results] == [
        ("https://a.test", "snip", "tavily", 1)
    ]
    assert route.calls[0].request.headers["authorization"] == "Bearer key"
    assert json.loads(route.calls[0].request.content)["query"] == "q"


@respx.mock
def test_brave_and_serpapi_parsing():
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(
            200, json={"web": {"results": [{"title": "B", "url": "https://b.test", "description": "d"}]}}
        )
    )
    respx.get("https://serpapi.com/search.json").mock(
        return_value=httpx.Response(
            200, json={"organic_results": [{"title": "S", "link": "https://s.test", "snippet": "s"}]}
        )
    )

    async def go():
        async with httpx.AsyncClient() as client:
            return await BraveSearch("k", client).search("q"), await SerpAPISearch("k", client).search("q")

    brave, serp = run(go())
    assert brave[0].url == "https://b.test" and brave[0].snippet == "d"
    assert serp[0].url == "https://s.test" and serp[0].title == "S"


@respx.mock
def test_http_errors_become_search_errors():
    respx.post("https://api.tavily.com/search").mock(return_value=httpx.Response(401))

    async def go():
        async with httpx.AsyncClient() as client:
            return await TavilySearch("bad", client).search("q")

    with pytest.raises(SearchError, match="401"):
        run(go())


def test_provider_from_env():
    client = httpx.AsyncClient()
    assert provider_from_env(client, env={"BRAVE_API_KEY": "x"}).name == "brave"
    assert provider_from_env(client, env={"BRAVE_API_KEY": "x", "TAVILY_API_KEY": "y"}).name == "tavily"
    assert provider_from_env(client, "serpapi", env={"SERPAPI_API_KEY": "z"}).name == "serpapi"
    with pytest.raises(SearchError, match="--demo"):
        provider_from_env(client, env={})
    with pytest.raises(SearchError, match="BRAVE_API_KEY"):
        provider_from_env(client, "brave", env={"TAVILY_API_KEY": "y"})


def test_cached_search_skips_repeat_calls():
    class Counting:
        name = "count"
        calls = 0

        async def search(self, query, max_results=5):
            from research_agent.models import SearchResult

            self.calls += 1
            return [SearchResult("https://a.test", "A", "s", self.name, 1)]

    inner = Counting()
    cached = CachedSearch(inner, Cache(None))
    first = run(cached.search("q"))
    second = run(cached.search("q"))
    assert first == second and inner.calls == 1


def test_anthropic_request_shape():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})

    llm = AnthropicClient("sk-test", "model-x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete("hi", system="be brief") == "hello"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["body"]["model"] == "model-x" and seen["body"]["system"] == "be brief"


def test_openai_request_shape():
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"][0] == {"role": "system", "content": "s"}
        assert request.headers["authorization"] == "Bearer sk-o"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm = OpenAIClient("sk-o", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert llm.complete("p", system="s") == "ok"


def test_llm_from_env_selection():
    assert llm_from_env(env={}) is None
    assert llm_from_env(env={"OPENAI_API_KEY": "o"}).name == "openai"
    assert llm_from_env(env={"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a"}).name == "anthropic"
    assert llm_from_env("none", env={"ANTHROPIC_API_KEY": "a"}) is None
    assert llm_from_env(env={"ANTHROPIC_API_KEY": "a", "RESEARCH_LLM_MODEL": "m"}).model == "m"
    with pytest.raises(ValueError):
        llm_from_env("openai", env={"ANTHROPIC_API_KEY": "a"})
