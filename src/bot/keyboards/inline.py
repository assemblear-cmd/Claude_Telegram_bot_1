"""Inline keyboard builders for bot interactions."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_review_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Build approve/edit/reject keyboard for post review."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Approve",
                callback_data=f"post:approve:{post_id}",
            ),
            InlineKeyboardButton(
                text="Edit",
                callback_data=f"post:edit:{post_id}",
            ),
            InlineKeyboardButton(
                text="Reject",
                callback_data=f"post:reject:{post_id}",
            ),
        ]
    ])


def get_confirm_keyboard(action: str, post_id: int) -> InlineKeyboardMarkup:
    """Build confirmation keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Confirm",
                callback_data=f"confirm:{action}:{post_id}",
            ),
            InlineKeyboardButton(
                text="Cancel",
                callback_data=f"cancel:{action}:{post_id}",
            ),
        ]
    ])
