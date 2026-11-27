"""
Блокировка пользователей, забаненных в админ-панели (User.is_blocked).

Раньше флаг проверялся только в /start, и заблокированный пользователь
мог продолжать откликаться и создавать заявки через кнопки.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from config import ADMIN_IDS
from database import async_session
from services import UserService

BLOCKED_TEXT = (
    "❌ Ваш аккаунт заблокирован.\n"
    "Для получения подробной информации обратитесь к администратору."
)


class BlockedUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and user.id not in ADMIN_IDS:
            async with async_session() as session:
                blocked = await UserService.is_blocked(session, user.id)
            if blocked:
                if isinstance(event, CallbackQuery):
                    await event.answer(BLOCKED_TEXT, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(BLOCKED_TEXT)
                return None
        return await handler(event, data)
