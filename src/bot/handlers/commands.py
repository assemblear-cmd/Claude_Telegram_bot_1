"""Bot command handlers: /start, /help, /new_post, /status, /sources, /schedule."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from src.db import repository as repo
from src.db.models import Post, Source
from src.orchestrator.state import PipelineState

logger = logging.getLogger(__name__)

router = Router(name="commands")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Welcome message and help."""
    await message.answer(
        "<b>Telegram MultiAgent Publisher</b>\n\n"
        "Мультиагентная система автопостинга.\n\n"
        "<b>Команды:</b>\n"
        "/new_post &lt;тема&gt; — Создать новый пост\n"
        "/status — Статус всех постов\n"
        "/sources — Список источников\n"
        "/schedule — Расписание публикаций\n"
        "/help — Справка",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Detailed help."""
    await message.answer(
        "<b>Как это работает:</b>\n\n"
        "1. <code>/new_post AI trends 2025</code> — создаёт новый пост\n"
        "2. Система автоматически:\n"
        "   • Ищет релевантные источники\n"
        "   • Парсит контент\n"
        "   • Генерирует текст (3 этапа)\n"
        "   • Проверяет факты\n"
        "   • Расставляет ссылки\n"
        "3. Вам приходит пост на ревью с кнопками:\n"
        "   • <b>Approve</b> — одобрить и запланировать\n"
        "   • <b>Edit</b> — отправить правки\n"
        "   • <b>Reject</b> — отклонить\n\n"
        "Web-дашборд: http://localhost:8000/dashboard",
        parse_mode="HTML",
    )


@router.message(Command("new_post"))
async def cmd_new_post(message: Message, orchestrator: Any) -> None:
    """Create a new post. Usage: /new_post <topic>."""
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await message.answer(
            "Использование: <code>/new_post &lt;тема&gt;</code>\n"
            "Пример: <code>/new_post Нейросети в медицине</code>",
            parse_mode="HTML",
        )
        return

    topic = args[1].strip()
    await message.answer(f"Создаю пост по теме: <b>{topic}</b>\nЗапускаю конвейер...", parse_mode="HTML")

    try:
        post_id = await orchestrator.create_post(topic)
        await message.answer(
            f"Пост #{post_id} создан. Конвейер запущен.\n"
            "Вы получите уведомление когда пост будет готов к ревью.",
            parse_mode="HTML",
        )
        # Run pipeline in background (don't await in handler)
        import asyncio
        asyncio.create_task(orchestrator.run_full_pipeline(post_id))
    except Exception as e:
        logger.exception("Failed to create post: %s", e)
        await message.answer(f"Ошибка: {e}")


@router.message(Command("status"))
async def cmd_status(message: Message, session_factory: Any) -> None:
    """Show status of all posts."""
    async with session_factory() as session:
        posts = await repo.list_ordered(
            session, Post, order_by=Post.created_at.desc(), limit=20
        )

    if not posts:
        await message.answer("Нет постов.")
        return

    lines = ["<b>Последние посты:</b>\n"]
    for p in posts:
        state_emoji = _state_emoji(p.pipeline_state)
        topic_short = p.topic[:40]
        scheduled = ""
        if p.scheduled_at:
            scheduled = f" | {p.scheduled_at.strftime('%d.%m %H:%M')}"
        lines.append(
            f"{state_emoji} <b>#{p.id}</b> {topic_short}\n"
            f"   <code>{p.pipeline_state}</code>{scheduled}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("sources"))
async def cmd_sources(message: Message, session_factory: Any) -> None:
    """List sources."""
    async with session_factory() as session:
        sources = await repo.list_ordered(
            session, Source, order_by=Source.created_at.desc(), limit=20
        )

    if not sources:
        await message.answer("Нет сохранённых источников.")
        return

    lines = ["<b>Источники:</b>\n"]
    for s in sources:
        wl = " [WL]" if s.is_whitelisted else ""
        lines.append(
            f"• <b>{s.domain}</b>{wl} ({s.trust_score:.1f})\n"
            f"  {s.topic} — {s.url[:60]}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, session_factory: Any) -> None:
    """Show upcoming scheduled posts."""
    async with session_factory() as session:
        posts = await repo.list_all(
            session, Post, pipeline_state=PipelineState.SCHEDULED.value
        )

    if not posts:
        await message.answer("Нет запланированных постов.")
        return

    lines = ["<b>Запланированные посты:</b>\n"]
    for p in sorted(posts, key=lambda x: x.scheduled_at or ""):
        time_str = p.scheduled_at.strftime("%d.%m.%Y %H:%M") if p.scheduled_at else "?"
        lines.append(f"• #{p.id} — {p.topic[:40]} | {time_str}")

    await message.answer("\n".join(lines), parse_mode="HTML")


def _state_emoji(state: str) -> str:
    mapping = {
        "created": "🆕",
        "researching": "🔍",
        "parsing": "📄",
        "writing": "✍️",
        "fact_checking": "🔬",
        "inserting_links": "🔗",
        "pending_review": "👁",
        "admin_editing": "✏️",
        "scheduling": "📅",
        "scheduled": "⏰",
        "publishing": "📤",
        "published": "✅",
        "rejected": "❌",
        "failed": "💥",
    }
    return mapping.get(state, "❓")
