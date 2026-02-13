"""Admin-specific command handlers."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router(name="admin")


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Show the user's Telegram ID (for config setup)."""
    await message.answer(
        f"Your Telegram ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


@router.message(Command("pipeline"))
async def cmd_pipeline(message: Message, session_factory: Any) -> None:
    """Show pipeline state machine info."""
    from src.orchestrator.state import PipelineState

    states = "\n".join(f"  • {s.value}" for s in PipelineState)
    await message.answer(
        f"<b>Pipeline States:</b>\n{states}",
        parse_mode="HTML",
    )
