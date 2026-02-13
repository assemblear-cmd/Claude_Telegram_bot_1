"""Application entrypoint: boots bot, web dashboard, scheduler, and orchestrator."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from src.config import get_settings, setup_logging, DATA_DIR

logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize all components and run them concurrently."""
    # 1. Setup
    setup_logging()
    settings = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting Telegram MultiAgent Publisher...")

    # 2. Database
    from src.db.engine import init_db
    session_factory = await init_db(settings.database_url)

    # 3. Seed default schedule slots
    await _seed_schedule_slots(session_factory, settings)

    # 4. Services
    from src.services.claude_client import ClaudeClient
    from src.services.link_validator import LinkValidatorService
    from src.services.pdf_extractor import PdfExtractorService
    from src.services.scraper import ScraperService
    from src.services.web_search import WebSearchService
    from src.services.youtube_transcript import YouTubeTranscriptService

    claude = ClaudeClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        default_model=settings.get_agent_config("writer").get(
            "claude_model", "claude-sonnet-4-5-20250929"
        ),
    )
    web_search = WebSearchService(
        tavily_api_key=settings.tavily_api_key.get_secret_value(),
        engine=settings.get_agent_config("researcher").get("search_engine", "tavily"),
    )
    scraper = ScraperService(
        user_agent=settings.get_agent_config("parser").get("user_agent", "Bot/1.0"),
        timeout=settings.get_agent_config("parser").get("request_timeout", 30),
    )
    pdf_extractor = PdfExtractorService()
    youtube = YouTubeTranscriptService()
    link_validator = LinkValidatorService(
        timeout=settings.get_agent_config("link_inserter").get("link_check_timeout", 10)
    )

    # 5. Telegram Bot
    from src.bot.setup import create_bot
    bot = create_bot(settings.telegram_bot_token.get_secret_value())

    # 6. Agents
    from src.agents.content_parser import ContentParser
    from src.agents.content_writer import ContentWriter
    from src.agents.fact_checker import FactChecker
    from src.agents.link_inserter import LinkInserter
    from src.agents.post_scheduler import PostScheduler
    from src.agents.publisher import Publisher
    from src.agents.source_researcher import SourceResearcher

    agents = {
        "source_researcher": SourceResearcher(
            settings.get_agent_config("researcher"), web_search
        ),
        "content_parser": ContentParser(
            settings.get_agent_config("parser"), scraper, pdf_extractor, youtube
        ),
        "content_writer": ContentWriter(
            settings.get_agent_config("writer"), claude
        ),
        "fact_checker": FactChecker(
            settings.get_agent_config("fact_checker"), claude
        ),
        "link_inserter": LinkInserter(
            settings.get_agent_config("link_inserter"), claude, link_validator
        ),
        "post_scheduler": PostScheduler(
            settings.get_agent_config("scheduler")
        ),
        "publisher": Publisher(
            settings.get_agent_config("publisher"),
            bot,
            settings.admin_ids_list,
            settings.telegram_channel_id,
        ),
    }

    # 7. Orchestrator
    from src.orchestrator.editor import EditorOrchestrator
    orchestrator = EditorOrchestrator(agents, session_factory, settings.pipeline)

    # 8. Scheduler service
    from src.services.scheduler_service import SchedulerService
    scheduler_service = SchedulerService(orchestrator, session_factory)

    # 9. Dispatcher
    from src.bot.setup import create_dispatcher
    dp = create_dispatcher(orchestrator, session_factory, settings.admin_ids_list)

    # 10. Web app
    from src.web.app import create_web_app
    web_app = create_web_app(orchestrator, session_factory, scheduler_service)

    # 11. Start everything
    logger.info("All components initialized. Starting services...")

    # Start scheduler
    await scheduler_service.start()

    # Create tasks
    bot_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False)
    )

    config = uvicorn.Config(
        web_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    web_task = asyncio.create_task(server.serve())

    logger.info(
        "Bot polling started. Web dashboard at http://%s:%d",
        settings.web_host, settings.web_port,
    )

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(*_):
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            signal.signal(sig, handle_signal)

    # Wait for shutdown
    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass

    # Cleanup
    logger.info("Shutting down...")
    await scheduler_service.stop()
    await dp.stop_polling()
    server.should_exit = True
    await bot.session.close()

    from src.db.engine import close_db
    await close_db()
    logger.info("Shutdown complete")


async def _seed_schedule_slots(session_factory, settings) -> None:
    """Create default schedule slots if none exist."""
    from src.db.models import ScheduleSlot
    from src.db import repository as repo

    async with session_factory() as session:
        existing = await repo.list_all(session, ScheduleSlot)
        if existing:
            return

        scheduler_config = settings.get_agent_config("scheduler")
        default_slots = scheduler_config.get("default_slots", [])
        tz = scheduler_config.get("timezone", "Europe/Moscow")

        for slot_cfg in default_slots:
            slot = ScheduleSlot(
                day_of_week=slot_cfg["day"],
                time_utc=slot_cfg["time"],
                timezone=tz,
                is_active=True,
            )
            session.add(slot)

        await session.commit()
        if default_slots:
            logger.info("Seeded %d default schedule slots", len(default_slots))


def run() -> None:
    """Entry point for the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
