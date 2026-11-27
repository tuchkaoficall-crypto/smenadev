"""
Точка входа для запуска админ-панели
"""
import logging
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
from admin import app
from config import ADMIN_HOST, ADMIN_PORT, DEBUG

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/admin.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    # 0.0.0.0 означает «все интерфейсы», в браузере открываем через 127.0.0.1
    browser_host = "127.0.0.1" if ADMIN_HOST in ("0.0.0.0", "::", "") else ADMIN_HOST
    url = f"http://{browser_host}:{ADMIN_PORT}"
    logger.info(f"Запуск админ-панели на {ADMIN_HOST}:{ADMIN_PORT}")
    # В debug-режиме Flask перезапускает скрипт, печатаем адрес только один раз
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        print(f"\n  Админ-панель: {url}\n  Вход: {url}/auth/login\n", flush=True)
    logger.info(f"Debug режим: {DEBUG}")
    
    app.run(
        host=ADMIN_HOST,
        port=ADMIN_PORT,
        debug=DEBUG
    )
