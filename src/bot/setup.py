"""Bot and Dispatcher factory."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers import admin, callbacks, commands
from src.bot.middlewares.auth import AdminOnlyMiddleware

logger = logging.getLogger(__name__)


def create_bot(token: str) -> Bot:
    """Create the aiogram Bot instance."""
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def create_dispatcher(
    orchestrator: Any,
    session_factory: Any,
    admin_ids: list[int],
) -> Dispatcher:
    """Create and configure the Dispatcher with all routers."""
    dp = Dispatcher(storage=MemoryStorage())

    # Register middlewares
    if admin_ids:
        dp.message.middleware(AdminOnlyMiddleware(admin_ids))
        dp.callback_query.middleware(AdminOnlyMiddleware(admin_ids))

    # Register routers
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(admin.router)

    # Inject dependencies
    dp["orchestrator"] = orchestrator
    dp["session_factory"] = session_factory

    logger.info("Dispatcher configured with %d routers", 3)
    return dp
