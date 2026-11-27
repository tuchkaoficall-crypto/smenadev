"""
Сборка диспетчера aiogram: middleware и роутеры в правильном порядке.
Используется в run_bot.py и в тестах (tests/), чтобы проверять бота целиком.
"""
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage


def build_dispatcher() -> Dispatcher:
    from bot.handlers import start, employer, worker, worker_tools, admin, order_form
    from bot.middlewares.blocked import BlockedUserMiddleware

    dp = Dispatcher(storage=MemoryStorage())
    # Заблокированные в админке пользователи не могут пользоваться ботом
    dp.message.outer_middleware(BlockedUserMiddleware())
    dp.callback_query.outer_middleware(BlockedUserMiddleware())

    # Регистрация роутеров (ВАЖЕН ПОРЯДОК!)
    dp.include_router(start.router)
    dp.include_router(worker.router)        # worker РАНЬШЕ employer
    dp.include_router(worker_tools.router)  # отметка на смене, документы, смена города
    dp.include_router(employer.router)
    dp.include_router(order_form.router)    # после employer: кнопки меню важнее ввода в форме
    dp.include_router(admin.router)
    return dp
