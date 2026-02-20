"""Agent 4: Content Writer — 3-stage content creation using Gemini API."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, PostSource, RawMaterial
from src.services.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class ContentWriter(BaseAgent):
    """3-stage content creation: concept → draft → formatted Telegram post."""

    def __init__(self, config: dict[str, Any], gemini: GeminiClient):
        super().__init__(config)
        self.gemini = gemini
        self.model = config.get("gemini_model", "gemini-2.0-flash")
        self.max_tokens_concept = config.get("max_tokens_concept", 200)
        self.max_tokens_draft = config.get("max_tokens_draft", 2000)
        self.max_tokens_format = config.get("max_tokens_format", 1500)
        self.max_chars = config.get("telegram_max_chars", 4096)
        self.style_guide = config.get("style_guide", "")
        self.prompts = config.get("prompts", {})

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        # Load associated materials
        materials_text = await self._get_materials_text(session, post_id)

        # Check if we're in a re-write loop (admin edit or fact-check feedback)
        admin_notes = post.admin_notes
        fact_notes = post.fact_check_notes

        # Stage 1: Concept bullet (skip if already exists and no re-write needed)
        if not post.concept_bullet or admin_notes:
            concept = await self._generate_concept(post.topic, materials_text, admin_notes)
            post.concept_bullet = concept
        else:
            concept = post.concept_bullet

        # Stage 2: Draft text
        draft = await self._generate_draft(
            concept, materials_text, admin_notes, fact_notes
        )
        post.draft_text = draft

        # Stage 3: Format for Telegram
        formatted = await self._format_for_telegram(draft)
        post.formatted_text = formatted

        # Clear admin notes after processing
        if admin_notes:
            post.admin_notes = None

        await session.flush()

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={
                "concept_length": len(concept),
                "draft_length": len(draft),
                "formatted_length": len(formatted),
            },
        )

    async def _generate_concept(
        self, topic: str, materials: str, admin_notes: str | None = None
    ) -> str:
        """Stage 1: Generate a single-sentence concept."""
        prompt_template = self.prompts.get("concept", "")
        prompt = self.gemini.render_prompt(
            prompt_template, topic=topic, materials=materials[:5000]
        )
        if admin_notes:
            prompt += f"\n\nУчти следующие правки от редактора:\n{admin_notes}"

        return await self.gemini.complete(
            prompt, model=self.model, max_tokens=self.max_tokens_concept
        )

    async def _generate_draft(
        self,
        concept: str,
        materials: str,
        admin_notes: str | None = None,
        fact_notes: str | None = None,
    ) -> str:
        """Stage 2: Generate full draft from concept."""
        prompt_template = self.prompts.get("draft", "")
        prompt = self.gemini.render_prompt(
            prompt_template,
            concept=concept,
            materials=materials[:8000],
            style_guide=self.style_guide,
        )
        if admin_notes:
            prompt += f"\n\nПравки редактора:\n{admin_notes}"
        if fact_notes:
            prompt += f"\n\nЗамечания фактчекера (исправь эти проблемы):\n{fact_notes}"

        return await self.gemini.complete(
            prompt, model=self.model, max_tokens=self.max_tokens_draft
        )

    async def _format_for_telegram(self, draft: str) -> str:
        """Stage 3: Format draft for Telegram."""
        prompt_template = self.prompts.get("format", "")
        prompt = self.gemini.render_prompt(
            prompt_template, draft=draft, max_chars=self.max_chars
        )
        return await self.gemini.complete(
            prompt, model=self.model, max_tokens=self.max_tokens_format
        )

    async def _get_materials_text(self, session: AsyncSession, post_id: int) -> str:
        """Load and concatenate materials for the post."""
        stmt = (
            select(RawMaterial)
            .join(PostSource, PostSource.material_id == RawMaterial.id)
            .where(PostSource.post_id == post_id)
            .order_by(PostSource.relevance_score.desc())
        )
        result = await session.execute(stmt)
        materials = result.scalars().all()

        if not materials:
            return "Нет доступных материалов."

        parts = []
        for m in materials[:5]:  # Top 5 most relevant
            header = f"[Источник: {m.source_url}]"
            # Limit each material to 3000 chars
            text = m.raw_text[:3000] if m.raw_text else ""
            parts.append(f"{header}\n{text}")

        return "\n\n---\n\n".join(parts)
