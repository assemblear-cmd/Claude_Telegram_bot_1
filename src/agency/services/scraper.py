"""Scraping service: fetches photos and stories from model Instagram accounts."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.agency import repository as repo
from src.agency.models import AgencyModel
from src.agency.services.instagram_client import InstagramClient

logger = logging.getLogger(__name__)

MEDIA_DIR = Path("data/agency/photos")


class AgencyScraperService:
    """Scrapes Instagram profiles for model photos and stories."""

    def __init__(self, ig_client: InstagramClient, media_dir: Path = MEDIA_DIR) -> None:
        self._ig = ig_client
        self._media_dir = media_dir

    async def scrape_model(
        self,
        session: AsyncSession,
        model: AgencyModel,
        max_posts: int = 20,
    ) -> int:
        """Scrape recent photos from a single model. Returns count of new items."""
        new_count = 0
        try:
            medias = self._ig.get_user_medias(model.username, amount=max_posts)
            for media in medias:
                if media.media_type != 1:  # 1 = photo
                    continue

                media_pk = str(media.pk)
                existing = await repo.get_media_by_instagram_pk(session, media_pk)
                if existing:
                    continue

                # Download photo
                model_dir = self._media_dir / model.username
                local_path = self._ig.download_media(media_pk, model_dir)

                thumbnail_url = str(media.thumbnail_url) if media.thumbnail_url else None
                media_url = thumbnail_url or ""

                await repo.create_media(
                    session,
                    model_id=model.id,
                    instagram_media_pk=media_pk,
                    media_type="photo",
                    media_url=media_url,
                    local_path=str(local_path) if local_path else None,
                    thumbnail_url=thumbnail_url,
                    caption=media.caption_text,
                )
                new_count += 1

            # Scrape stories
            stories = self._ig.get_user_stories(model.username)
            for story in stories:
                if story.media_type != 1:  # photo stories only
                    continue

                story_pk = str(story.pk)
                existing = await repo.get_media_by_instagram_pk(session, story_pk)
                if existing:
                    continue

                model_dir = self._media_dir / model.username / "stories"
                local_path = self._ig.download_story(story_pk, model_dir)
                thumb = str(story.thumbnail_url) if story.thumbnail_url else ""

                await repo.create_media(
                    session,
                    model_id=model.id,
                    instagram_media_pk=story_pk,
                    media_type="story",
                    media_url=thumb,
                    local_path=str(local_path) if local_path else None,
                    thumbnail_url=thumb,
                )
                new_count += 1

            await repo.update_model(
                session,
                model.id,
                last_scraped_at=datetime.utcnow(),
                scrape_error=None,
            )
            await session.commit()
            logger.info("Scraped @%s: %d new items", model.username, new_count)

        except Exception as exc:
            await session.rollback()
            await repo.update_model(
                session,
                model.id,
                scrape_error=str(exc),
                last_scraped_at=datetime.utcnow(),
            )
            await session.commit()
            logger.exception("Error scraping @%s", model.username)

        return new_count

    async def scrape_all_models(
        self,
        session: AsyncSession,
        max_posts_per_model: int = 20,
    ) -> dict[str, int]:
        """Scrape all active models. Returns {username: new_count}."""
        models = await repo.list_models(session, active_only=True)
        results: dict[str, int] = {}
        for model in models:
            count = await self.scrape_model(session, model, max_posts=max_posts_per_model)
            results[model.username] = count
        return results

    def get_user_info(self, username: str) -> dict | None:
        """Fetch public profile info for a username."""
        return self._ig.get_user_info(username)
