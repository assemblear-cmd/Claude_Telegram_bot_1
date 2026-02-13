"""APScheduler service for scheduled post publication."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from src.db.models import Post
from src.orchestrator.state import PipelineState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from src.orchestrator.editor import EditorOrchestrator

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled post publication using APScheduler."""

    def __init__(
        self,
        orchestrator: EditorOrchestrator,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.orchestrator = orchestrator
        self.session_factory = session_factory
        self.scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        """Start the scheduler and load pending scheduled posts."""
        self.scheduler.start()
        await self._load_scheduled_posts()
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Shutdown the scheduler."""
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    def schedule_post(self, post_id: int, scheduled_at: datetime) -> None:
        """Register a job to publish a post at the scheduled time."""
        job_id = f"publish_post_{post_id}"

        # Remove existing job if any
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Ensure datetime is timezone-aware
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        # Don't schedule in the past
        now = datetime.now(timezone.utc)
        if scheduled_at <= now:
            logger.warning(
                "Post #%d scheduled_at is in the past (%s), publishing immediately",
                post_id, scheduled_at,
            )
            self.scheduler.add_job(
                self._publish_job,
                "date",
                run_date=now,
                args=[post_id],
                id=job_id,
            )
        else:
            self.scheduler.add_job(
                self._publish_job,
                trigger=DateTrigger(run_date=scheduled_at),
                args=[post_id],
                id=job_id,
            )

        logger.info("Scheduled post #%d for %s", post_id, scheduled_at)

    async def _publish_job(self, post_id: int) -> None:
        """Job function: publish a scheduled post."""
        logger.info("Publishing scheduled post #%d", post_id)
        try:
            await self.orchestrator.publish_post(post_id)
        except Exception as e:
            logger.exception("Failed to publish post #%d: %s", post_id, e)

    async def _load_scheduled_posts(self) -> None:
        """On startup, load all SCHEDULED posts and register their jobs."""
        async with self.session_factory() as session:
            stmt = (
                select(Post)
                .where(Post.pipeline_state == PipelineState.SCHEDULED.value)
                .where(Post.scheduled_at.isnot(None))
            )
            result = await session.execute(stmt)
            posts = result.scalars().all()

        for post in posts:
            self.schedule_post(post.id, post.scheduled_at)

        if posts:
            logger.info("Loaded %d scheduled posts", len(posts))
