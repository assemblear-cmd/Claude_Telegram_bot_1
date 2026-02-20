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
    from src.services.gemini_client import GeminiClient
    from src.services.link_validator import LinkValidatorService
    from src.services.pdf_extractor import PdfExtractorService
    from src.services.scraper import ScraperService
    from src.services.web_search import WebSearchService
    from src.services.youtube_transcript import YouTubeTranscriptService

    gemini = GeminiClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        default_model=settings.get_agent_config("writer").get(
            "gemini_model", "gemini-2.0-flash"
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
            settings.get_agent_config("writer"), gemini
        ),
        "fact_checker": FactChecker(
            settings.get_agent_config("fact_checker"), gemini
        ),
        "link_inserter": LinkInserter(
            settings.get_agent_config("link_inserter"), gemini, link_validator
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

    # 8a. Agency42 services
    agency_scheduler = None
    if settings.ig_username and settings.ig_password.get_secret_value():
        from src.agency.services.instagram_client import InstagramClient
        from src.agency.services.photo_analyzer import PhotoAnalyzerService
        from src.agency.services.scheduler import AgencySchedulerService

        ig_client = InstagramClient(
            username=settings.ig_username,
            password=settings.ig_password.get_secret_value(),
        )
        photo_analyzer = PhotoAnalyzerService(
            api_key=settings.gemini_api_key.get_secret_value(),
        )
        agency_scheduler = AgencySchedulerService(
            session_factory=session_factory,
            ig_client=ig_client,
            analyzer=photo_analyzer,
        )
        logger.info("Agency42 module initialized for @%s", settings.ig_username)
    else:
        logger.info("Agency42 module disabled (no IG credentials)")

    # 8b. Seed agency models
    await _seed_agency_models(session_factory)

    # 9. Dispatcher
    from src.bot.setup import create_dispatcher
    dp = create_dispatcher(orchestrator, session_factory, settings.admin_ids_list)

    # 10. Web app
    from src.web.app import create_web_app
    web_app = create_web_app(
        orchestrator, session_factory, scheduler_service, agency_scheduler
    )

    # 11. Start everything
    logger.info("All components initialized. Starting services...")

    # Start scheduler
    await scheduler_service.start()

    # Start agency scheduler
    if agency_scheduler:
        await agency_scheduler.start()

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
    if agency_scheduler:
        await agency_scheduler.stop()
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


async def _seed_agency_models(session_factory) -> None:
    """Seed the initial list of model Instagram accounts."""
    from src.agency.models import AgencyModel
    from src.agency import repository as agency_repo

    INITIAL_MODELS = [
        ("fluently.jess", "https://www.instagram.com/fluently.jess"),
        ("lerabuns", "https://www.instagram.com/lerabuns"),
        ("michellefromchina", "https://www.instagram.com/michellefromchina"),
        ("alina_vesneva", "https://www.instagram.com/alina_vesneva"),
        ("mayalanez_", "https://www.instagram.com/mayalanez_"),
        ("monicaoffchello", "https://www.instagram.com/monicaoffchello"),
        ("luanamsantillan", "https://www.instagram.com/luanamsantillan"),
        ("marysmithfairy", "https://www.instagram.com/marysmithfairy"),
        ("emiliaabrookss", "https://www.instagram.com/emiliaabrookss"),
        ("morelita.xo", "https://www.instagram.com/morelita.xo"),
        ("josee.steelman", "https://www.instagram.com/josee.steelman"),
        ("dps999k", "https://www.instagram.com/dps999k"),
        ("sophiie_xdt", "https://www.instagram.com/sophiie_xdt"),
        ("yourlittlesnake", "https://www.instagram.com/yourlittlesnake"),
        ("virginiaa.nucci", "https://www.instagram.com/virginiaa.nucci"),
        ("carolinezalog", "https://www.instagram.com/carolinezalog"),
        ("da_rach3l", "https://www.instagram.com/da_rach3l"),
        ("rachelc00k", "https://www.instagram.com/rachelc00k"),
        ("minaashofficial", "https://www.instagram.com/minaashofficial"),
        ("chennuanyang", "https://www.instagram.com/chennuanyang"),
        ("linabelfiore", "https://www.instagram.com/linabelfiore"),
        ("reneeherbert_", "https://www.instagram.com/reneeherbert_"),
        ("samantha.baio", "https://www.instagram.com/samantha.baio"),
        ("minaxash", "https://www.instagram.com/minaxash"),
    ]

    async with session_factory() as session:
        existing = await agency_repo.list_models(session)
        if existing:
            return

        for username, url in INITIAL_MODELS:
            await agency_repo.create_model(
                session,
                username=username,
                instagram_url=url,
            )

        await session.commit()
        logger.info("Seeded %d agency models", len(INITIAL_MODELS))


def run() -> None:
    """Entry point for the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
