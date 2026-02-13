"""Link validation service: checks if URLs are accessible."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class LinkValidatorService:
    """Validate URLs by sending HEAD requests."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    async def is_valid(self, url: str) -> bool:
        """Check if a URL is accessible (returns 2xx or 3xx)."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                response = await client.head(url)
                if response.status_code >= 400:
                    # Some servers don't support HEAD, try GET
                    response = await client.get(url, headers={"Range": "bytes=0-0"})
                return response.status_code < 400
        except Exception as e:
            logger.warning("Link validation failed for %s: %s", url, e)
            return False

    async def validate_batch(self, urls: list[str]) -> dict[str, bool]:
        """Validate multiple URLs concurrently."""
        import asyncio

        tasks = {url: asyncio.create_task(self.is_valid(url)) for url in urls}
        results = {}
        for url, task in tasks.items():
            results[url] = await task
        return results
