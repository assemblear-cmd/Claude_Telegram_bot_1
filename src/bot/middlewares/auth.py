"""Admin-only authentication middleware."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class AdminOnlyMiddleware(BaseMiddleware):
    """Allow only admin users to interact with the bot."""

    def __init__(self, admin_ids: list[int]):
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id if event.from_user else None

        if not user_id or user_id not in self.admin_ids:
            if isinstance(event, Message):
                await event.answer(
                    "Access denied. You are not an admin.\n"
                    f"Your ID: {user_id}"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("Access denied.", show_alert=True)
            return None

        return await handler(event, data)
