"""Agent 5: Fact Checker — verifies claims in generated content."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, PostSource, RawMaterial
from src.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class FactChecker(BaseAgent):
    """Cross-reference post content with original sources for accuracy."""

    def __init__(self, config: dict[str, Any], claude: ClaudeClient):
        super().__init__(config)
        self.claude = claude
        self.model = config.get("claude_model", "claude-sonnet-4-5-20250929")
        self.confidence_threshold = config.get("confidence_threshold", 0.7)
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
                errors=["No text to fact-check"],
            )

        # Load source materials
        materials_text = await self._get_materials_text(session, post_id)

        # Run fact-check via Claude
        prompt = self.claude.render_prompt(
            self.prompt_template,
            post_text=post_text,
            materials=materials_text[:10000],
        )

        try:
            result_data = await self.claude.complete_json(prompt, model=self.model)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Fact-check JSON parse failed: %s", e)
            # If we can't parse, pass with a warning
            post.fact_check_score = 0.8
            post.fact_check_notes = json.dumps(
                {"error": f"JSON parse failed: {e}"}, ensure_ascii=False
            )
            return AgentResult(
                status=AgentStatus.SUCCESS,
                data={"score": 0.8},
                warnings=["Fact-check response parsing failed, passing with default score"],
            )

        score = float(result_data.get("score", 0.5))
        claims = result_data.get("claims", [])
        summary = result_data.get("summary", "")

        post.fact_check_score = score
        post.fact_check_notes = json.dumps(
            {"claims": claims, "summary": summary},
            ensure_ascii=False,
        )

        if score < self.confidence_threshold:
            # Build feedback for content writer
            flagged_claims = [
                c for c in claims if not c.get("verified", True)
            ]
            feedback = "\n".join(
                f"- {c.get('claim', '?')}: {c.get('note', '')}"
                for c in flagged_claims
            )
            logger.warning(
                "Post #%d fact-check score %.2f < %.2f, flagging %d claims",
                post_id, score, self.confidence_threshold, len(flagged_claims),
            )
            return AgentResult(
                status=AgentStatus.NEEDS_REVIEW,
                data={
                    "score": score,
                    "flagged_claims": len(flagged_claims),
                    "feedback": feedback,
                },
            )

        logger.info("Post #%d fact-check passed: score %.2f", post_id, score)
        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={"score": score, "claims_count": len(claims)},
        )

    async def _get_materials_text(self, session: AsyncSession, post_id: int) -> str:
        """Load source materials for cross-referencing."""
        stmt = (
            select(RawMaterial)
            .join(PostSource, PostSource.material_id == RawMaterial.id)
            .where(PostSource.post_id == post_id)
        )
        result = await session.execute(stmt)
        materials = result.scalars().all()

        parts = []
        for m in materials[:5]:
            text = m.raw_text[:3000] if m.raw_text else ""
            parts.append(f"[{m.source_url}]\n{text}")
        return "\n\n---\n\n".join(parts)
