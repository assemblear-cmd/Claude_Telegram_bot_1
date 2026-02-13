"""Web scraping service: httpx + BeautifulSoup content extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from src.utils.retry import with_retry
from src.utils.text import clean_text

logger = logging.getLogger(__name__)


@dataclass
class ScrapedContent:
    url: str
    title: str
    text: str
    content_type: str = "web_page"
    metadata: dict | None = None


class ScraperService:
    """Scrape web pages and extract clean text content."""

    def __init__(self, user_agent: str = "TelegramMultiAgentBot/1.0", timeout: int = 30):
        self.user_agent = user_agent
        self.timeout = timeout

    @with_retry(max_attempts=2, min_wait=2, max_wait=10)
    async def scrape_url(self, url: str, max_length: int = 50000) -> ScrapedContent:
        """Scrape a web page and return cleaned text."""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)

        # Try article content first, then body
        article = soup.find("article")
        if article:
            text = article.get_text(separator="\n", strip=True)
        else:
            body = soup.find("body")
            text = body.get_text(separator="\n", strip=True) if body else soup.get_text(
                separator="\n", strip=True
            )

        text = clean_text(text)
        if len(text) > max_length:
            text = text[:max_length]

        logger.info("Scraped %s: %d chars, title='%s'", url, len(text), title[:50])
        return ScrapedContent(
            url=url,
            title=title,
            text=text,
            content_type="web_page",
            metadata={"status_code": response.status_code, "char_count": len(text)},
        )
