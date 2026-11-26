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

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.bot_instance import bot
from bot.handlers import start, employer, worker, admin
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
    
    # Создание диспетчера
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация роутеров (ВАЖЕН ПОРЯДОК!)
    dp.include_router(start.router)
    dp.include_router(worker.router)  # worker РАНЬШЕ employer
    dp.include_router(employer.router)
    dp.include_router(admin.router)
    
    logger.info("Роутеры зарегистрированы")
    
    # Устанавливаем команды бота
    from aiogram.types import BotCommand, BotCommandScopeDefault
    
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="help", description="❓ Помощь и инструкции"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="support", description="💬 Связаться с поддержкой"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
    ]
    
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Команды бота установлены")
    
    # Запуск polling
    try:
        logger.info("Бот запущен и готов к работе")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем")
