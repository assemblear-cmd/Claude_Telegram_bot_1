"""Agent 2: Content Parser — scrapes and extracts content from sources."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, PostSource, RawMaterial, Source
from src.services.pdf_extractor import PdfExtractorService
from src.services.scraper import ScraperService
from src.services.youtube_transcript import YouTubeTranscriptService

logger = logging.getLogger(__name__)


class ContentParser(BaseAgent):
    """Scrape/parse content from sources and store as raw materials."""

    def __init__(
        self,
        config: dict[str, Any],
        scraper: ScraperService,
        pdf_extractor: PdfExtractorService,
        youtube_service: YouTubeTranscriptService,
    ):
        super().__init__(config)
        self.scraper = scraper
        self.pdf_extractor = pdf_extractor
        self.youtube = youtube_service
        self.max_content_length = config.get("max_content_length", 50000)
        self.supported_types = config.get("supported_types", ["web_page", "pdf", "youtube"])

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        # Get sources for this topic
        stmt = select(Source).where(Source.topic == post.topic).order_by(
            Source.trust_score.desc()
        )
        result = await session.execute(stmt)
        sources = result.scalars().all()

        if not sources:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=["No sources to parse"],
            )

        parsed_count = 0
        errors = []
        warnings = []

        for source in sources[:10]:  # Limit to top 10 sources
            try:
                content_type, text = await self._extract_content(source.url)
                if not text:
                    warnings.append(f"Empty content from {source.url}")
                    continue

                # Truncate if needed
                if len(text) > self.max_content_length:
                    text = text[: self.max_content_length]

                # Create raw material
                material = RawMaterial(
                    source_id=source.id,
                    source_url=source.url,
                    content_type=content_type,
                    raw_text=text,
                    metadata_json=json.dumps({
                        "title": source.title,
                        "domain": source.domain,
                        "char_count": len(text),
                    }),
                )
                session.add(material)
                await session.flush()

                # Link material to post
                post_source = PostSource(
                    post_id=post_id,
                    material_id=material.id,
                    relevance_score=source.trust_score,
                )
                session.add(post_source)
                parsed_count += 1

            except Exception as e:
                warnings.append(f"Failed to parse {source.url}: {e}")
                logger.warning("Failed to parse %s: %s", source.url, e)

        if parsed_count == 0:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=["Could not parse any sources"],
                warnings=warnings,
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={"parsed_count": parsed_count, "total_sources": len(sources)},
            warnings=warnings,
        )

    async def _extract_content(self, url: str) -> tuple[str, str]:
        """Detect content type and extract text."""
        url_lower = url.lower()

        if url_lower.endswith(".pdf"):
            text = await self.pdf_extractor.extract_from_url(url)
            return "pdf", text

        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            text = await self.youtube.get_transcript(url)
            return "youtube", text

        # Default: web page
        scraped = await self.scraper.scrape_url(url, self.max_content_length)
        return "web_page", scraped.text
