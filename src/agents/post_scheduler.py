"""Agent 3: Post Scheduler — finds the next available time slot for publication."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post, ScheduleSlot

logger = logging.getLogger(__name__)


class PostScheduler(BaseAgent):
    """Find the next available schedule slot and assign it to the post."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.tz_name = config.get("timezone", "Europe/Moscow")
        self.tz = ZoneInfo(self.tz_name)

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        # Get active schedule slots
        stmt = (
            select(ScheduleSlot)
            .where(ScheduleSlot.is_active == True)  # noqa: E712
            .order_by(ScheduleSlot.priority.desc())
        )
        result = await session.execute(stmt)
        slots = result.scalars().all()

        if not slots:
            # No slots configured — schedule for 1 hour from now
            scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)
            post.scheduled_at = scheduled_at
            return AgentResult(
                status=AgentStatus.SUCCESS,
                data={
                    "scheduled_at": scheduled_at.isoformat(),
                    "note": "No slots configured, defaulted to 1 hour from now",
                },
            )

        # Get all already-scheduled post times
        scheduled_stmt = (
            select(Post.scheduled_at)
            .where(Post.pipeline_state.in_(["scheduled", "publishing"]))
            .where(Post.scheduled_at.isnot(None))
        )
        scheduled_result = await session.execute(scheduled_stmt)
        occupied_times = {
            row[0].date() if row[0] else None for row in scheduled_result
        }

        # Find next available slot
        now = datetime.now(self.tz)
        scheduled_at = self._find_next_slot(slots, now, occupied_times)

        if not scheduled_at:
            # All slots occupied for next week — schedule 24h from now
            scheduled_at = datetime.now(timezone.utc) + timedelta(hours=24)

        post.scheduled_at = scheduled_at

        local_time = scheduled_at.astimezone(self.tz)
        logger.info(
            "Post #%d scheduled for %s (%s)",
            post_id, local_time.strftime("%Y-%m-%d %H:%M"), self.tz_name,
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={
                "scheduled_at": scheduled_at.isoformat(),
                "local_time": local_time.strftime("%Y-%m-%d %H:%M %Z"),
            },
        )

    def _find_next_slot(
        self,
        slots: list[ScheduleSlot],
        now: datetime,
        occupied_dates: set,
    ) -> datetime | None:
        """Find the next available slot in the next 14 days."""
        for day_offset in range(14):
            candidate_date = now.date() + timedelta(days=day_offset)
            weekday = candidate_date.weekday()

            for slot in slots:
                if slot.day_of_week != weekday:
                    continue

                hour, minute = map(int, slot.time_utc.split(":"))
                candidate = datetime(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    hour,
                    minute,
                    tzinfo=self.tz,
                )

                # Skip past times
                if candidate <= now:
                    continue

                # Skip occupied dates (simple dedup)
                if candidate_date in occupied_dates:
                    continue

                return candidate.astimezone(timezone.utc)

        return None
