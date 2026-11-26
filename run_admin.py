"""
Точка входа для запуска админ-панели
"""
import logging
from admin import app, login_manager
from admin.models import AdminUser
from config import ADMIN_HOST, ADMIN_PORT, DEBUG

# Настройка логирования
logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/admin.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    # В нашем случае всего один администратор
    if int(user_id) == 1:
        from config import ADMIN_USERNAME
        return AdminUser(id=1, username=ADMIN_USERNAME)
    return None


if __name__ == '__main__':
    logger.info(f"Запуск админ-панели на {ADMIN_HOST}:{ADMIN_PORT}")
    logger.info(f"Debug режим: {DEBUG}")
    
    app.run(
        host=ADMIN_HOST,
        port=ADMIN_PORT,
        debug=DEBUG
    )
