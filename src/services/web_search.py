"""Web search service: Tavily API wrapper with DuckDuckGo fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.utils.retry import with_retry

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0


class WebSearchService:
    """Search the web using Tavily API, with DuckDuckGo HTML fallback."""

    def __init__(self, tavily_api_key: str = "", engine: str = "tavily"):
        self.tavily_api_key = tavily_api_key
        self.engine = engine

    async def search(
        self, query: str, max_results: int = 10
    ) -> list[SearchResult]:
        """Search for a query and return results."""
        if self.engine == "tavily" and self.tavily_api_key:
            return await self._search_tavily(query, max_results)
        return await self._search_duckduckgo(query, max_results)

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def _search_tavily(
        self, query: str, max_results: int
    ) -> list[SearchResult]:
        """Search using Tavily API."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                score=item.get("score", 0.0),
            ))
        logger.info("Tavily search '%s': %d results", query, len(results))
        return results

    async def _search_duckduckgo(
        self, query: str, max_results: int
    ) -> list[SearchResult]:
        """Fallback: search using DuckDuckGo Instant Answer API."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("RelatedTopics", [])[:max_results]:
            if "FirstURL" in item:
                results.append(SearchResult(
                    title=item.get("Text", "")[:100],
                    url=item["FirstURL"],
                    snippet=item.get("Text", ""),
                    score=0.5,
                ))
        logger.info("DuckDuckGo search '%s': %d results", query, len(results))
        return results
