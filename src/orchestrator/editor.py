"""Editor/Orchestrator: drives the pipeline state machine."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import PipelineEvent, Post
from src.orchestrator.pipeline import TRANSITIONS
from src.orchestrator.state import PAUSE_STATES, PipelineState

logger = logging.getLogger(__name__)


class EditorOrchestrator:
    """Agent 8: Orchestrates the entire pipeline.

    This is NOT a BaseAgent subclass — it is the controller that
    invokes agents. It owns the state machine transitions.
    """

    def __init__(
        self,
        agents: dict[str, BaseAgent],
        session_factory: async_sessionmaker[AsyncSession],
        pipeline_config: dict[str, Any] | None = None,
    ):
        self.agents = agents
        self.session_factory = session_factory
        self.pipeline_config = pipeline_config or {}
        self.max_fact_check_loops = self.pipeline_config.get("max_fact_check_loops", 3)

    async def create_post(self, topic: str) -> int:
        """Create a new post and return its ID."""
        async with self.session_factory() as session:
            post = Post(topic=topic, pipeline_state=PipelineState.CREATED.value)
            session.add(post)
            event = PipelineEvent(
                post_id=0,  # will be set after flush
                from_state=None,
                to_state=PipelineState.CREATED.value,
                agent_name="orchestrator",
                details=json.dumps({"topic": topic}),
            )
            await session.flush()
            event.post_id = post.id
            session.add(event)
            await session.commit()
            logger.info("Created post #%d with topic: %s", post.id, topic)
            return post.id

    async def advance(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run the next agent in the pipeline for the given post."""
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=[f"Post {post_id} not found"],
            )

        current_state = PipelineState(post.pipeline_state)

        if current_state not in TRANSITIONS:
            return AgentResult(
                status=AgentStatus.SKIPPED,
                data={"reason": f"No transition from {current_state.value}"},
            )

        agent_key, next_state = TRANSITIONS[current_state]
        agent = self.agents.get(agent_key)
        if not agent:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=[f"Agent '{agent_key}' not found"],
            )

        logger.info(
            "Post #%d: %s -> running %s -> %s",
            post_id, current_state.value, agent_key, next_state.value,
        )

        result = await agent.run(session, post_id, context)

        if result.status == AgentStatus.SUCCESS:
            post.pipeline_state = next_state.value
            await self._log_transition(
                session, post_id, current_state.value, next_state.value, agent_key, result
            )
        elif result.status == AgentStatus.NEEDS_REVIEW:
            # Fact checker flagged issues — loop back to writing
            loop_count = await self._count_fact_check_loops(session, post_id)
            if loop_count < self.max_fact_check_loops:
                post.pipeline_state = PipelineState.WRITING.value
                await self._log_transition(
                    session, post_id, current_state.value,
                    PipelineState.WRITING.value, agent_key, result,
                )
                logger.warning(
                    "Post #%d: fact-check loop %d/%d, returning to writing",
                    post_id, loop_count + 1, self.max_fact_check_loops,
                )
            else:
                # Force to review even with low score
                post.pipeline_state = PipelineState.INSERTING_LINKS.value
                await self._log_transition(
                    session, post_id, current_state.value,
                    PipelineState.INSERTING_LINKS.value, agent_key, result,
                )
                logger.warning(
                    "Post #%d: max fact-check loops reached, forcing forward",
                    post_id,
                )
        else:
            post.pipeline_state = PipelineState.FAILED.value
            await self._log_transition(
                session, post_id, current_state.value,
                PipelineState.FAILED.value, agent_key, result,
            )

        await session.commit()
        return result

    async def run_full_pipeline(self, post_id: int) -> None:
        """Run the pipeline until it reaches a pause/terminal state."""
        async with self.session_factory() as session:
            while True:
                post = await session.get(Post, post_id)
                if not post:
                    break
                state = PipelineState(post.pipeline_state)
                if state in PAUSE_STATES:
                    logger.info("Post #%d paused at %s", post_id, state.value)
                    break
                result = await self.advance(session, post_id)
                if result.status == AgentStatus.FAILURE:
                    break
                if result.status == AgentStatus.SKIPPED:
                    break

    async def handle_admin_decision(
        self,
        post_id: int,
        decision: str,
        edit_text: str | None = None,
    ) -> None:
        """Handle admin approve/reject/edit from bot or web."""
        async with self.session_factory() as session:
            post = await session.get(Post, post_id)
            if not post:
                logger.error("Post %d not found for admin decision", post_id)
                return

            if decision == "approve":
                post.pipeline_state = PipelineState.SCHEDULING.value
                await self._log_transition(
                    session, post_id, PipelineState.PENDING_REVIEW.value,
                    PipelineState.SCHEDULING.value, "admin",
                    AgentResult(status=AgentStatus.SUCCESS, data={"decision": "approve"}),
                )
                await session.commit()
                # Run scheduler
                result = await self.advance(session, post_id)
                if result.status != AgentStatus.SUCCESS:
                    logger.error("Failed to schedule post #%d", post_id)

            elif decision == "reject":
                post.pipeline_state = PipelineState.REJECTED.value
                await self._log_transition(
                    session, post_id, PipelineState.PENDING_REVIEW.value,
                    PipelineState.REJECTED.value, "admin",
                    AgentResult(status=AgentStatus.SUCCESS, data={"decision": "reject"}),
                )
                await session.commit()

            elif decision == "edit":
                post.admin_notes = edit_text
                post.pipeline_state = PipelineState.WRITING.value
                await self._log_transition(
                    session, post_id, PipelineState.PENDING_REVIEW.value,
                    PipelineState.WRITING.value, "admin",
                    AgentResult(
                        status=AgentStatus.SUCCESS,
                        data={"decision": "edit", "notes": edit_text},
                    ),
                )
                await session.commit()

            # If edit, re-run pipeline from writing
            if decision == "edit":
                await self.run_full_pipeline(post_id)

    async def publish_post(self, post_id: int) -> None:
        """Transition a scheduled post to publishing and then published."""
        async with self.session_factory() as session:
            post = await session.get(Post, post_id)
            if not post or post.pipeline_state != PipelineState.SCHEDULED.value:
                return

            publisher = self.agents.get("publisher")
            if not publisher:
                logger.error("Publisher agent not found")
                return

            post.pipeline_state = PipelineState.PUBLISHING.value
            await session.commit()

            result = await publisher.run(session, post_id, {"action": "publish"})
            if result.status == AgentStatus.SUCCESS:
                post.pipeline_state = PipelineState.PUBLISHED.value
                await self._log_transition(
                    session, post_id, PipelineState.PUBLISHING.value,
                    PipelineState.PUBLISHED.value, "publisher", result,
                )
            else:
                post.pipeline_state = PipelineState.FAILED.value
                await self._log_transition(
                    session, post_id, PipelineState.PUBLISHING.value,
                    PipelineState.FAILED.value, "publisher", result,
                )
            await session.commit()

    async def _log_transition(
        self,
        session: AsyncSession,
        post_id: int,
        from_state: str | None,
        to_state: str,
        agent_name: str,
        result: AgentResult,
    ) -> None:
        event = PipelineEvent(
            post_id=post_id,
            from_state=from_state,
            to_state=to_state,
            agent_name=agent_name,
            details=json.dumps({
                "status": result.status.value,
                "data": result.data,
                "errors": result.errors,
                "warnings": result.warnings,
                "time_ms": round(result.execution_time_ms, 1),
            }, ensure_ascii=False, default=str),
        )
        session.add(event)

    async def _count_fact_check_loops(
        self, session: AsyncSession, post_id: int
    ) -> int:
        """Count how many times fact_checker has sent post back to writing."""
        stmt = (
            select(PipelineEvent)
            .where(PipelineEvent.post_id == post_id)
            .where(PipelineEvent.agent_name == "fact_checker")
            .where(PipelineEvent.to_state == PipelineState.WRITING.value)
        )
        result = await session.execute(stmt)
        return len(result.scalars().all())
