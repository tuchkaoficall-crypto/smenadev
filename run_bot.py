"""
Точка входа для запуска Telegram бота
"""
import asyncio
import logging
import sys
import os

# Исправление кодировки для Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from bot.bot_instance import bot
from database import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота"""
    logger.info("Запуск бота СМЕНА...")
    
    # Инициализация базы данных
    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных инициализирована")
    from database import async_session
    from services import cities
    async with async_session() as session:
        logger.info("Города: %s", ", ".join(await cities.refresh_async(session)))
    
    # Диспетчер: middleware и роутеры (порядок важен, см. bot/dispatcher.py)
    from bot.dispatcher import build_dispatcher
    dp = build_dispatcher()

    logger.info("Роутеры зарегистрированы")
    
    # Устанавливаем команды бота
    from aiogram.types import BotCommand, BotCommandScopeDefault
    
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="help", description="❓ Помощь и инструкции"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="invite", description="🎁 Пригласить друга"),
        BotCommand(command="support", description="💬 Связаться с поддержкой"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
    ]
    
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Команды бота установлены")
    
    # Напоминания о сменах (фоновая задача)
    from bot.utils.scheduler import reminder_loop
    reminders = asyncio.create_task(reminder_loop())

    # Запуск polling
    try:
        logger.info("Бот запущен и готов к работе")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reminders.cancel()
        await bot.session.close()
        from database import engine
        await engine.dispose()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем")
