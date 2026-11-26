"""
Инстанс бота для использования в других модулях
"""
from aiogram import Bot
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
