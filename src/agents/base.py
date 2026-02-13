"""Base agent interface and result types."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PipelineEvent

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"


@dataclass
class AgentResult:
    """Standardized return from every agent execution."""

    status: AgentStatus
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseAgent(ABC):
    """Abstract base for all agents.

    Each agent is a callable unit invoked by the orchestrator.
    Agents receive context (post_id, session, config) and return AgentResult.
    Agents do NOT call other agents — only the orchestrator does routing.
    Agents are stateless between invocations; all state lives in the DB.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.name = self.__class__.__name__

    async def run(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Wrapper that measures time and catches exceptions."""
        start = time.monotonic()
        try:
            result = await self.execute(session, post_id, context)
            result.execution_time_ms = (time.monotonic() - start) * 1000
            logger.info(
                "%s completed for post %d: %s (%.0fms)",
                self.name, post_id, result.status.value, result.execution_time_ms,
            )
            return result
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.exception("%s failed for post %d: %s", self.name, post_id, e)
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=[str(e)],
                execution_time_ms=elapsed,
            )

    @abstractmethod
    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run this agent's task for the given post."""
        ...

    async def log_event(
        self,
        session: AsyncSession,
        post_id: int,
        from_state: str | None,
        to_state: str,
        details: str = "",
    ) -> None:
        """Write a row to pipeline_events for audit trail."""
        event = PipelineEvent(
            post_id=post_id,
            from_state=from_state,
            to_state=to_state,
            agent_name=self.name,
            details=details,
        )
        session.add(event)
