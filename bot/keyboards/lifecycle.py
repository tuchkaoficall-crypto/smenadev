"""
Превращение списков кнопок из services.order_keyboards в aiogram-разметку
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def to_markup(rows) -> InlineKeyboardMarkup | None:
    rows = [row for row in (rows or []) if row]
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def yes_no(yes_text: str, yes_data: str, no_text: str = "↩️ Нет, назад", no_data: str = "noop") -> InlineKeyboardMarkup:
    return to_markup([[(yes_text, yes_data), (no_text, no_data)]])
