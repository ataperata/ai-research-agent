"""Web search providers. Each one maps a vendor's JSON into SearchResult objects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from ..cache import Cache
from ..models import SearchResult


class SearchError(RuntimeError):
    pass


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


class _HTTPProvider:
    name = "base"

    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self.api_key = api_key
        self.client = client

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise SearchError(f"{self.name} returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"{self.name} request failed: {exc}") from exc

    def _results(self, rows: list[dict], url_key: str, snippet_key: str, limit: int) -> list[SearchResult]:
        out = []
        for row in rows:
            url = row.get(url_key)
            if not url or not str(url).startswith(("http://", "https://")):
                continue
            out.append(
                SearchResult(
                    url=url,
                    title=(row.get("title") or url).strip(),
                    snippet=(row.get(snippet_key) or "").strip(),
                    provider=self.name,
                    rank=len(out) + 1,
                )
            )
            if len(out) >= limit:
                break
        return out


class TavilySearch(_HTTPProvider):
    name = "tavily"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = await self._request(
            "POST",
            "https://api.tavily.com/search",
            json={"query": query, "max_results": max_results, "search_depth": "basic"},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self._results(data.get("results", []), "url", "content", max_results)


class BraveSearch(_HTTPProvider):
    name = "brave"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = await self._request(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        return self._results(data.get("web", {}).get("results", []), "url", "description", max_results)


class SerpAPISearch(_HTTPProvider):
    name = "serpapi"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = await self._request(
            "GET",
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "num": max_results, "api_key": self.api_key},
        )
        return self._results(data.get("organic_results", []), "link", "snippet", max_results)


PROVIDERS: dict[str, tuple[type[_HTTPProvider], str]] = {
    "tavily": (TavilySearch, "TAVILY_API_KEY"),
    "brave": (BraveSearch, "BRAVE_API_KEY"),
    "serpapi": (SerpAPISearch, "SERPAPI_API_KEY"),
}


def provider_from_env(
    client: httpx.AsyncClient, preferred: str | None = None, env: Mapping[str, str] | None = None
) -> SearchProvider:
    """Return the preferred provider, or the first one with an API key in the environment."""
    env = os.environ if env is None else env
    choice = (preferred or env.get("RESEARCH_SEARCH", "")).strip().lower()
    names = [choice] if choice else list(PROVIDERS)
    for name in names:
        if name not in PROVIDERS:
            raise SearchError(f"unknown search provider {name!r}; choose from {', '.join(PROVIDERS)}")
        cls, key_var = PROVIDERS[name]
        key = env.get(key_var)
        if key:
            return cls(key, client)
        if choice:
            raise SearchError(f"{key_var} is not set")
    raise SearchError(
        "no search API key found. Set TAVILY_API_KEY, BRAVE_API_KEY or SERPAPI_API_KEY, "
        "or run `research --demo` for the offline demo."
    )


class CachedSearch:
    """Wraps any provider so repeat queries come from the cache."""

    def __init__(self, inner: SearchProvider, cache: Cache):
        self.inner = inner
        self.cache = cache
        self.name = inner.name

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        key = f"{self.inner.name}|{max_results}|{query}"
        cached = self.cache.get("search", key)
        if cached is not None:
            return [SearchResult(**row) for row in cached]
        results = await self.inner.search(query, max_results)
        self.cache.set("search", key, [r.__dict__ for r in results])
        return results
