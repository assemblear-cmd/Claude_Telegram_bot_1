"""Callback query handlers for inline keyboard buttons."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router(name="callbacks")


class EditPostStates(StatesGroup):
    """FSM states for editing a post."""
    waiting_for_edit = State()


@router.callback_query(F.data.startswith("post:"))
async def handle_post_action(
    callback: CallbackQuery,
    state: FSMContext,
    orchestrator: Any,
) -> None:
    """Handle approve/edit/reject button clicks."""
    if not callback.data:
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid action", show_alert=True)
        return

    _, action, post_id_str = parts
    try:
        post_id = int(post_id_str)
    except ValueError:
        await callback.answer("Invalid post ID", show_alert=True)
        return

    if action == "approve":
        await callback.answer("Approving...")
        await callback.message.edit_text(
            callback.message.text + "\n\n<b>✅ APPROVED</b>",
            parse_mode="HTML",
        )
        import asyncio
        asyncio.create_task(orchestrator.handle_admin_decision(post_id, "approve"))

    elif action == "reject":
        await callback.answer("Rejected")
        await callback.message.edit_text(
            callback.message.text + "\n\n<b>❌ REJECTED</b>",
            parse_mode="HTML",
        )
        await orchestrator.handle_admin_decision(post_id, "reject")

    elif action == "edit":
        await callback.answer("Send your edit notes...")
        await state.set_state(EditPostStates.waiting_for_edit)
        await state.update_data(post_id=post_id)
        await callback.message.answer(
            f"Отправьте правки для поста #{post_id}.\n"
            "Напишите, что нужно изменить:",
        )


@router.message(EditPostStates.waiting_for_edit)
async def handle_edit_text(
    message: Message,
    state: FSMContext,
    orchestrator: Any,
) -> None:
    """Receive edit text and re-run pipeline."""
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await message.answer("Ошибка: ID поста не найден.")
        await state.clear()
        return

    edit_text = message.text or ""
    await state.clear()

    await message.answer(
        f"Правки для поста #{post_id} приняты. Перегенерация...\n"
        f"Правки: {edit_text[:200]}",
    )

    import asyncio
    asyncio.create_task(
        orchestrator.handle_admin_decision(post_id, "edit", edit_text)
    )
