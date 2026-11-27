"""
Конфигурация приложения СМЕНА
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# Telegram Bot настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
CHANNEL_URL = "https://t.me/smenawork_ru"
CHANNEL_ID = "@smenawork_ru"  # Или числовой ID канала
ADMIN_CONTACT = "@smena_adm"  # Контакт администратора

# База данных - Используем SQLite для локальной разработки
USE_SQLITE = os.getenv("USE_SQLITE", "True").lower() == "true"

if USE_SQLITE:
    # SQLite для локальной разработки. SQLITE_PATH позволяет указать другой файл
    # (например, отдельную базу для тестов), по умолчанию smena_db.sqlite в корне проекта.
    SQLITE_PATH = os.getenv("SQLITE_PATH") or str(BASE_DIR / "smena_db.sqlite")
    DATABASE_URL = f"sqlite+aiosqlite:///{SQLITE_PATH}"
    SYNC_DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
else:
    # PostgreSQL для продакшена
    DB_CONFIG = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 5432)),
        "database": os.getenv("DB_NAME", "smena_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }
    
    # Формирование DATABASE_URL
    DATABASE_URL = (
        f"postgresql+asyncpg://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )
    
    # Синхронный URL для Alembic и Flask
    SYNC_DATABASE_URL = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )

# Admin Panel
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "dev-secret-key-change-in-production")
ADMIN_HOST = os.getenv("ADMIN_HOST", "0.0.0.0")
ADMIN_PORT = int(os.getenv("ADMIN_PORT", 5000))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# Платежи
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "")

# Приложение
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Комиссии (процентная система)
# Базовая комиссия: 10%
# Если смена < 2500₽: 5%
# Если смена > 4500₽: 12.5%
BASE_COMMISSION_PERCENT = 10.0
LOW_AMOUNT_COMMISSION_PERCENT = 5.0
HIGH_AMOUNT_COMMISSION_PERCENT = 12.5
LOW_AMOUNT_THRESHOLD = 2500
HIGH_AMOUNT_THRESHOLD = 4500
PREPAYMENT_PERCENT = int(os.getenv("PREPAYMENT_PERCENT", 50))


def calculate_commission(shift_amount: float) -> float:
    """
    Расчет комиссии в зависимости от суммы смены
    
    Args:
        shift_amount: Сумма оплаты за смену
        
    Returns:
        Размер комиссии в рублях
    """
    if shift_amount < LOW_AMOUNT_THRESHOLD:
        return shift_amount * (LOW_AMOUNT_COMMISSION_PERCENT / 100)
    elif shift_amount > HIGH_AMOUNT_THRESHOLD:
        return shift_amount * (HIGH_AMOUNT_COMMISSION_PERCENT / 100)
    else:
        return shift_amount * (BASE_COMMISSION_PERCENT / 100)

def calculate_order_cost(
    payment_type: str,
    payment_amount: float,
    shift_duration: int,
    workers_needed: int,
) -> dict:
    """
    Единый расчёт стоимости заявки (используется и в боте, и в OrderService,
    чтобы работодателю показывалась та же сумма, что пишется в БД).

    Комиссия считается от оплаты одного работника за смену
    (для почасовой оплаты: ставка * часы), затем умножается на число работников.
    """
    if payment_type == "per_hour":
        shift_amount = payment_amount * shift_duration
    else:
        shift_amount = payment_amount

    commission_per_worker = calculate_commission(shift_amount)
    commission_total = commission_per_worker * workers_needed
    total_per_worker = shift_amount + commission_per_worker

    return {
        "shift_amount": shift_amount,
        "commission_per_worker": commission_per_worker,
        "commission_total": commission_total,
        "total_per_worker": total_per_worker,
        "total_cost": total_per_worker * workers_needed,
        "prepayment": commission_total * PREPAYMENT_PERCENT / 100,
    }


# Логи
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Статические файлы
STATIC_DIR = BASE_DIR / "admin" / "static"
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", str(BASE_DIR / "assets")))

# Города (для первого запуска)
AVAILABLE_CITIES = [
    "Петрозаводск",
]

# Категории работ
JOB_CATEGORIES = [
    "Грузчик",
    "Курьер",
    "Промоутер",
    "Официант",
    "Уборщик",
    "Разнорабочий",
    "Мерчендайзер",
    "Комплектовщик",
    "Другое",
]

# Статусы заказов
class OrderStatus:
    CREATED = "created"                    # Создан
    MODERATION = "moderation"              # На модерации
    SEARCH_WORKERS = "search_workers"      # Поиск работников
    CONFIRM_WORKERS = "confirm_workers"    # Подтверждение работников
    PREPAYMENT = "prepayment"              # Ожидание предоплаты
    SHIFT_STARTED = "shift_started"        # Смена началась
    SHIFT_COMPLETED = "shift_completed"    # Смена завершена
    PAYMENT_COMPLETED = "payment_completed" # Расчёт закрыт
    CANCELLED = "cancelled"                 # Отменён

ORDER_STATUS_NAMES = {
    OrderStatus.CREATED: "Создан",
    OrderStatus.MODERATION: "На модерации",
    OrderStatus.SEARCH_WORKERS: "Поиск работников",
    OrderStatus.CONFIRM_WORKERS: "Подтверждение работников",
    OrderStatus.PREPAYMENT: "Ожидание предоплаты",
    OrderStatus.SHIFT_STARTED: "Смена началась",
    OrderStatus.SHIFT_COMPLETED: "Смена завершена",
    OrderStatus.PAYMENT_COMPLETED: "Расчёт закрыт",
    OrderStatus.CANCELLED: "Отменён",
}

# Статусы откликов
class ResponseStatus:
    PENDING = "pending"           # Ожидает рассмотрения
    CONTACTED = "contacted"       # Администратор связался
    CONFIRMED = "confirmed"       # Подтверждён
    REJECTED = "rejected"         # Отклонён
    COMPLETED = "completed"       # Смена завершена
    WITHDRAWN = "withdrawn"       # Работник сам отказался
    NO_SHOW = "no_show"           # Не вышел на смену (отмечает администратор)

RESPONSE_STATUS_NAMES = {
    ResponseStatus.PENDING: "Ожидает рассмотрения",
    ResponseStatus.CONTACTED: "Администратор связался",
    ResponseStatus.CONFIRMED: "Подтверждён",
    ResponseStatus.REJECTED: "Отклонён",
    ResponseStatus.COMPLETED: "Смена завершена",
    ResponseStatus.WITHDRAWN: "Отказался",
    ResponseStatus.NO_SHOW: "Не вышел на смену",
}

# ==== Отметка «я на месте» ====
# Кнопку «📍 Я на месте» присылаем за CHECKIN_PROMPT_MINUTES до начала смены,
# опоздание считается после CHECKIN_GRACE_MINUTES от начала.
CHECKIN_PROMPT_MINUTES = int(os.getenv("CHECKIN_PROMPT_MINUTES", 30))
CHECKIN_GRACE_MINUTES = int(os.getenv("CHECKIN_GRACE_MINUTES", 15))
# Если у заказа задана точка на карте: дальше этого расстояния отметка помечается «далеко»
CHECKIN_MAX_DISTANCE_M = int(os.getenv("CHECKIN_MAX_DISTANCE_M", 500))

# ==== Надёжность работников ====
PENALTY_POINTS = {
    "late_cancel": 2,       # отказ от подтверждённой смены менее чем за 24 ч
    "very_late_cancel": 3,  # отказ менее чем за 3 ч
    "no_show": 5,           # не вышел на смену
    "late_checkin": 1,      # отметился «на месте» с опозданием
    "manual": 1,            # вручную из админ-панели (баллы задаёт админ)
}
PENALTY_NAMES = {
    "late_cancel": "Поздний отказ (< 24 ч)",
    "very_late_cancel": "Очень поздний отказ (< 3 ч)",
    "no_show": "Неявка на смену",
    "late_checkin": "Опоздание",
    "manual": "Штраф администратора",
}
PENALTY_WINDOW_DAYS = int(os.getenv("PENALTY_WINDOW_DAYS", 90))      # баллы «сгорают» через N дней
PENALTY_RESTRICT_POINTS = int(os.getenv("PENALTY_RESTRICT_POINTS", 10))  # от N баллов — без вакансий
# Надёжные работники получают вакансию сразу, остальные — через N минут (0 — всем сразу)
PRIORITY_DELAY_MINUTES = int(os.getenv("PRIORITY_DELAY_MINUTES", 15))

# Документы для проверки личности
DOCUMENT_TYPES = {
    "passport": "Паспорт",
    "medbook": "Медицинская книжка",
    "other": "Другой документ",
}
DOCUMENT_STATUS_NAMES = {"pending": "На проверке", "approved": "Подтверждён", "rejected": "Отклонён"}

# ==== Реферальная программа ====
REFERRAL_BONUS = float(os.getenv("REFERRAL_BONUS", 300))  # ₽ пригласившему за активного друга
REFERRAL_STATUS_NAMES = {
    "invited": "Зарегистрировался",
    "qualified": "Бонус начислен",
    "paid": "Бонус выплачен",
    "rejected": "Отклонён",
}

# Роли пользователей
class UserRole:
    EMPLOYER = "employer"
    WORKER = "worker"
    ADMIN = "admin"

USER_ROLE_NAMES = {
    UserRole.EMPLOYER: "Работодатель",
    UserRole.WORKER: "Работник",
    UserRole.ADMIN: "Администратор",
}

# Статусы проверки работодателей
class EmployerStatus:
    PENDING = "pending"       # Ожидает проверки
    APPROVED = "approved"     # Одобрен
    REJECTED = "rejected"     # Отклонён
    BLOCKED = "blocked"       # Заблокирован

EMPLOYER_STATUS_NAMES = {
    EmployerStatus.PENDING: "Ожидает проверки",
    EmployerStatus.APPROVED: "Одобрен",
    EmployerStatus.REJECTED: "Отклонён",
    EmployerStatus.BLOCKED: "Заблокирован",
}
