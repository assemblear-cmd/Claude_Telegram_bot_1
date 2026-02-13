"""Agent 1: Source Researcher — finds relevant sources for a topic."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, Source
from src.services.web_search import SearchResult, WebSearchService
from src.utils.text import extract_domain

logger = logging.getLogger(__name__)


class SourceResearcher(BaseAgent):
    """Search for relevant sources on the post's topic and store them in DB."""

    def __init__(self, config: dict[str, Any], search_service: WebSearchService):
        super().__init__(config)
        self.search = search_service
        self.max_sources = config.get("max_sources_per_topic", 10)
        self.min_trust_score = config.get("min_trust_score", 0.3)

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        topic = post.topic

        # Search for sources
        results = await self.search.search(topic, max_results=self.max_sources)
        if not results:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=[f"No sources found for topic: {topic}"],
            )

        # Also check existing whitelisted sources for this topic
        existing_stmt = (
            select(Source)
            .where(Source.topic == topic)
            .where(Source.is_whitelisted == True)  # noqa: E712
        )
        existing_result = await session.execute(existing_stmt)
        existing_sources = existing_result.scalars().all()

        # Store new sources
        new_count = 0
        for sr in results:
            if sr.score < self.min_trust_score:
                continue
            # Check if already exists
            stmt = select(Source).where(Source.url == sr.url)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                continue

            source = Source(
                url=sr.url,
                domain=extract_domain(sr.url),
                title=sr.title,
                topic=topic,
                trust_score=sr.score,
            )
            session.add(source)
            new_count += 1

        await session.flush()

        total = new_count + len(existing_sources)
        logger.info(
            "Post #%d: found %d new sources, %d existing for '%s'",
            post_id, new_count, len(existing_sources), topic,
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={
                "new_sources": new_count,
                "existing_sources": len(existing_sources),
                "total": total,
                "topic": topic,
            },
        )
