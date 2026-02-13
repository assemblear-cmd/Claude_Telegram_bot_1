"""Agent 7: Publisher — sends posts for review and publishes to channel."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import AgentResult, AgentStatus, BaseAgent
from src.db.models import Post
from src.utils.text import format_post_preview, truncate

logger = logging.getLogger(__name__)


class Publisher(BaseAgent):
    """Send post preview to admin for review, or publish to channel."""

    def __init__(
        self,
        config: dict[str, Any],
        bot: Bot,
        admin_ids: list[int],
        channel_id: int,
    ):
        super().__init__(config)
        self.bot = bot
        self.admin_ids = admin_ids
        self.channel_id = channel_id

    async def execute(
        self,
        session: AsyncSession,
        post_id: int,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        post = await session.get(Post, post_id)
        if not post:
            return AgentResult(status=AgentStatus.FAILURE, errors=["Post not found"])

        action = (context or {}).get("action", "review")

        if action == "publish":
            return await self._publish_to_channel(post)
        else:
            return await self._send_for_review(post)

    async def _send_for_review(self, post: Post) -> AgentResult:
        """Send post preview to all admins with approve/edit/reject buttons."""
        text = post.final_text or post.formatted_text or post.draft_text or ""

        preview = format_post_preview(
            post_id=post.id,
            topic=post.topic,
            text=truncate(text, 3500),
            fact_score=post.fact_check_score,
            state="pending_review",
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Approve",
                    callback_data=f"post:approve:{post.id}",
                ),
                InlineKeyboardButton(
                    text="Edit",
                    callback_data=f"post:edit:{post.id}",
                ),
                InlineKeyboardButton(
                    text="Reject",
                    callback_data=f"post:reject:{post.id}",
                ),
            ]
        ])

        sent_to = 0
        for admin_id in self.admin_ids:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=preview,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                sent_to += 1
            except Exception as e:
                logger.error("Failed to send review to admin %d: %s", admin_id, e)

        if sent_to == 0:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=["Could not send review to any admin"],
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            data={"sent_to_admins": sent_to},
        )

    async def _publish_to_channel(self, post: Post) -> AgentResult:
        """Publish the final text to the Telegram channel."""
        text = post.final_text or post.formatted_text or post.draft_text
        if not text:
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=["No text to publish"],
            )

        try:
            message = await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            post.telegram_message_id = message.message_id
            post.published_at = datetime.now(timezone.utc)

            logger.info(
                "Post #%d published to channel %d, msg_id=%d",
                post.id, self.channel_id, message.message_id,
            )
            return AgentResult(
                status=AgentStatus.SUCCESS,
                data={
                    "message_id": message.message_id,
                    "channel_id": self.channel_id,
                },
            )
        except Exception as e:
            logger.error("Failed to publish post #%d: %s", post.id, e)
            return AgentResult(
                status=AgentStatus.FAILURE,
                errors=[f"Telegram publish failed: {e}"],
            )
