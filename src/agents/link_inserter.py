"""Agent 6: Link Inserter — matches keywords to source URLs and inserts links."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, PostLink, PostSource, RawMaterial, Source
from src.services.claude_client import ClaudeClient
from src.services.link_validator import LinkValidatorService

logger = logging.getLogger(__name__)


class LinkInserter(BaseAgent):
    """Insert inline links into the post text using Claude to match keywords to sources."""

    def __init__(
        self,
        config: dict[str, Any],
        claude: ClaudeClient,
        link_validator: LinkValidatorService,
    ):
        super().__init__(config)
        self.claude = claude
        self.validator = link_validator
        self.model = config.get("claude_model", "claude-sonnet-4-5-20250929")
        self.max_links = config.get("max_links_per_post", 5)
        self.prompt_template = config.get("prompt", "")

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        post_text = post.formatted_text or post.draft_text
        if not post_text:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=["No text for link insertion"],
            )

        # Get available source URLs
        sources_info = await self._get_sources_info(session, post_id)
        if not sources_info:
            # No sources to link — just copy text to final
            post.final_text = post_text
            return AgentResult(
                status=AgentStatus.SUCCESS,
                data={"links_inserted": 0},
                warnings=["No sources available for linking"],
            )

        # Use Claude to find keywords for links
        prompt = self.claude.render_prompt(
            self.prompt_template,
            post_text=post_text,
            sources=sources_info,
            max_links=self.max_links,
        )

        try:
            links_data = await self.claude.complete_json(prompt, model=self.model)
        except Exception as e:
            logger.warning("Link insertion JSON parse failed: %s", e)
            post.final_text = post_text
            return AgentResult(
                status=AgentStatus.SUCCESS,
                data={"links_inserted": 0},
                warnings=[f"Could not parse link suggestions: {e}"],
            )

        if not isinstance(links_data, list):
            links_data = []

        # Validate links
        urls = [item.get("url", "") for item in links_data if item.get("url")]
        valid_urls = await self.validator.validate_batch(urls)

        # Insert valid links into text
        inserted = 0
        final_text = post_text
        for item in links_data:
            keyword = item.get("keyword", "")
            url = item.get("url", "")
            if not keyword or not url:
                continue
            if not valid_urls.get(url, False):
                logger.warning("Skipping invalid link: %s", url)
                continue
            if keyword in final_text:
                # Insert Telegram HTML link
                html_link = f'<a href="{url}">{keyword}</a>'
                final_text = final_text.replace(keyword, html_link, 1)

                # Store in DB
                post_link = PostLink(
                    post_id=post_id,
                    keyword=keyword,
                    url=url,
                    is_valid=True,
                )
                session.add(post_link)
                inserted += 1

        post.final_text = final_text
        await session.flush()

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={"links_inserted": inserted, "total_suggested": len(links_data)},
        )

    async def _get_sources_info(self, session: AsyncSession, post_id: int) -> str:
        """Build a text list of available sources for the prompt."""
        stmt = (
            select(Source)
            .join(RawMaterial, RawMaterial.source_id == Source.id)
            .join(PostSource, PostSource.material_id == RawMaterial.id)
            .where(PostSource.post_id == post_id)
        )
        result = await session.execute(stmt)
        sources = result.scalars().all()

        if not sources:
            return ""

        lines = []
        for s in sources:
            lines.append(f"- {s.title or s.domain}: {s.url}")
        return "\n".join(lines)
