"""Posting service: publishes photos to the agency's Instagram account."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.agency import repository as repo
from src.agency.models import AgencyPost, AgencySettings, ScrapedMedia
from src.agency.services.instagram_client import InstagramClient

logger = logging.getLogger(__name__)


class AgencyPosterService:
    """Handles posting curated photos to the agency Instagram account."""

    def __init__(self, ig_client: InstagramClient) -> None:
        self._ig = ig_client

    def _build_caption(self, template: str, media: ScrapedMedia) -> str:
        """Build caption from template, substituting model info."""
        return template.format(
            model_username=media.model.username if media.model else "model",
            model_name=media.model.full_name or media.model.username if media.model else "",
        )

    async def post_media(
        self,
        session: AsyncSession,
        media: ScrapedMedia,
        settings: AgencySettings,
    ) -> AgencyPost | None:
        """Post a single media item to the agency account."""
        if not media.local_path or not Path(media.local_path).exists():
            logger.error("No local file for media id=%d", media.id)
            return None

        caption = self._build_caption(settings.caption_template, media)

        # Create post record
        post = await repo.create_post(
            session,
            media_id=media.id,
            caption=caption,
            status="publishing",
        )
        await session.commit()

        # Upload to Instagram
        result = self._ig.upload_photo(Path(media.local_path), caption)

        if result:
            await repo.update_post(
                session,
                post.id,
                status="published",
                instagram_media_pk=str(result.pk),
                published_at=datetime.utcnow(),
            )
            await repo.update_media(session, media.id, is_posted=True, is_queued=False)
            await session.commit()
            logger.info("Published post id=%d, IG pk=%s", post.id, result.pk)
            return post
        else:
            await repo.update_post(
                session,
                post.id,
                status="failed",
                error_message="Upload failed — check logs for details",
            )
            await session.commit()
            logger.error("Failed to publish post id=%d", post.id)
            return None

    async def auto_post_next(self, session: AsyncSession) -> AgencyPost | None:
        """Automatically pick and post the next suitable photo."""
        settings = await repo.get_settings(session)
        if not settings.auto_posting_enabled:
            logger.debug("Auto-posting is disabled")
            return None

        # Check daily limit
        today_count = await repo.count_posts_today(session)
        if today_count >= settings.max_posts_per_day:
            logger.info("Daily post limit reached (%d/%d)", today_count, settings.max_posts_per_day)
            return None

        # Pick random suitable photo
        media = await repo.pick_random_suitable_media(session)
        if not media:
            logger.info("No suitable unposted media available")
            return None

        return await self.post_media(session, media, settings)
