"""Scheduler service for periodic scraping and auto-posting."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.agency import repository as repo
from src.agency.services.instagram_client import InstagramClient
from src.agency.services.photo_analyzer import PhotoAnalyzerService
from src.agency.services.poster import AgencyPosterService
from src.agency.services.scraper import AgencyScraperService

logger = logging.getLogger(__name__)


class AgencySchedulerService:
    """Manages periodic scraping, analysis, and posting jobs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ig_client: InstagramClient,
        analyzer: PhotoAnalyzerService,
    ) -> None:
        self._session_factory = session_factory
        self._ig_client = ig_client
        self._analyzer = analyzer
        self._scraper = AgencyScraperService(ig_client)
        self._poster = AgencyPosterService(ig_client)
        self._scheduler = AsyncIOScheduler()
        self._posting_job_id = "agency_auto_post"
        self._scraping_job_id = "agency_auto_scrape"
        self._analysis_job_id = "agency_auto_analyze"

    async def start(self) -> None:
        """Start the scheduler with current settings."""
        async with self._session_factory() as session:
            settings = await repo.get_settings(session)
            posting_minutes = settings.posting_interval_minutes
            scrape_minutes = settings.scrape_interval_minutes

        # Auto-post job
        self._scheduler.add_job(
            self._auto_post_job,
            "interval",
            minutes=posting_minutes,
            id=self._posting_job_id,
            replace_existing=True,
            misfire_grace_time=60,
        )

        # Auto-scrape job
        self._scheduler.add_job(
            self._auto_scrape_job,
            "interval",
            minutes=scrape_minutes,
            id=self._scraping_job_id,
            replace_existing=True,
            misfire_grace_time=120,
        )

        # Auto-analyze job (runs every 30 min)
        self._scheduler.add_job(
            self._auto_analyze_job,
            "interval",
            minutes=30,
            id=self._analysis_job_id,
            replace_existing=True,
            misfire_grace_time=60,
        )

        self._scheduler.start()
        logger.info(
            "Agency scheduler started: posting every %d min, scraping every %d min",
            posting_minutes,
            scrape_minutes,
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Agency scheduler stopped")

    async def reschedule(self) -> None:
        """Reload settings and reschedule jobs."""
        async with self._session_factory() as session:
            settings = await repo.get_settings(session)

        self._scheduler.reschedule_job(
            self._posting_job_id,
            trigger="interval",
            minutes=settings.posting_interval_minutes,
        )
        self._scheduler.reschedule_job(
            self._scraping_job_id,
            trigger="interval",
            minutes=settings.scrape_interval_minutes,
        )
        logger.info("Agency scheduler rescheduled")

    async def _auto_post_job(self) -> None:
        """Job: post next suitable photo."""
        try:
            async with self._session_factory() as session:
                settings = await repo.get_settings(session)
                if not settings.auto_posting_enabled:
                    return
                post = await self._poster.auto_post_next(session)
                if post:
                    logger.info("Auto-post completed: post id=%d", post.id)
        except Exception:
            logger.exception("Auto-post job failed")

    async def _auto_scrape_job(self) -> None:
        """Job: scrape all active models."""
        try:
            async with self._session_factory() as session:
                settings = await repo.get_settings(session)
                if not settings.auto_scrape_enabled:
                    return
                results = await self._scraper.scrape_all_models(session)
                total = sum(results.values())
                logger.info("Auto-scrape completed: %d new items from %d models", total, len(results))
        except Exception:
            logger.exception("Auto-scrape job failed")

    async def _auto_analyze_job(self) -> None:
        """Job: analyze unanalyzed photos."""
        try:
            async with self._session_factory() as session:
                count = await self._analyzer.analyze_unanalyzed(session)
                if count:
                    logger.info("Auto-analyze completed: %d photos analyzed", count)
        except Exception:
            logger.exception("Auto-analyze job failed")

    # Public methods for manual triggers

    async def trigger_scrape_all(self) -> dict[str, int]:
        async with self._session_factory() as session:
            return await self._scraper.scrape_all_models(session)

    async def trigger_scrape_model(self, model_id: int) -> int:
        async with self._session_factory() as session:
            model = await repo.get_model(session, model_id)
            if not model:
                return 0
            return await self._scraper.scrape_model(session, model)

    async def trigger_analyze(self, limit: int = 50) -> int:
        async with self._session_factory() as session:
            return await self._analyzer.analyze_unanalyzed(session, limit=limit)

    async def trigger_post(self) -> int | None:
        async with self._session_factory() as session:
            post = await self._poster.auto_post_next(session)
            return post.id if post else None
