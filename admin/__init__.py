"""
Flask админ-панель для СМЕНА
"""
import hmac
import logging
import secrets

from flask import Flask, session, request, abort
from flask_login import LoginManager
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from config import ADMIN_SECRET_KEY, SYNC_DATABASE_URL, ADMIN_PASSWORD, DEBUG

logger = logging.getLogger(__name__)

if ADMIN_SECRET_KEY == "dev-secret-key-change-in-production" or ADMIN_PASSWORD == "admin123":
    logger.warning(
        "⚠️ Админ-панель использует ключ/пароль по умолчанию. "
        "Задайте ADMIN_SECRET_KEY и ADMIN_PASSWORD в .env перед запуском на сервере!"
    )

# Создание приложения Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = ADMIN_SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = SYNC_DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка базы данных для Flask (синхронная)
engine = create_engine(SYNC_DATABASE_URL)
db_session = scoped_session(sessionmaker(bind=engine))

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Пожалуйста, войдите для доступа к этой странице.'

def get_or_404(model, object_id):
    """Аналог first_or_404 из Flask-SQLAlchemy для обычной scoped_session"""
    obj = db_session.get(model, object_id)
    if obj is None:
        abort(404)
    return obj


@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login.
    
    Определён здесь, а не в run_admin.py, чтобы работать и под gunicorn
    (gunicorn импортирует admin:app и run_admin.py не выполняет).
    """
    from admin.models import AdminUser
    from config import ADMIN_USERNAME
    if str(user_id) == "1":
        return AdminUser(id=1, username=ADMIN_USERNAME)
    return None


# ==== CSRF-защита форм ====

def _get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = _get_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf_token")
        form_token = request.form.get("csrf_token", "")
        if not token or not hmac.compare_digest(token, form_token):
            abort(400, description="CSRF token missing or invalid")


# Новые таблицы и колонки (журнал, рассылки, отметки, штрафы, документы, рефералы, города)
# создаются, только если их ещё нет. Существующие данные не трогаются.
from database.migrate import upgrade_schema  # noqa: E402
with engine.begin() as _conn:
    upgrade_schema(_conn)


# ==== Шаблонные фильтры и глобальные переменные ====

@app.template_filter("money")
def money_filter(value):
    try:
        return f"{float(value or 0):,.0f}".replace(",", " ") + " ₽"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("dt")
def dt_filter(value, fmt="%d.%m.%Y %H:%M"):
    return value.strftime(fmt) if value else "—"


@app.context_processor
def inject_globals():
    from admin import services
    from config import ORDER_STATUS_NAMES, RESPONSE_STATUS_NAMES, EMPLOYER_STATUS_NAMES
    from config import DOCUMENT_TYPES, DOCUMENT_STATUS_NAMES, PENALTY_NAMES, REFERRAL_STATUS_NAMES
    ctx = dict(
        ORDER_STATUS_NAMES=ORDER_STATUS_NAMES,
        RESPONSE_STATUS_NAMES=RESPONSE_STATUS_NAMES,
        EMPLOYER_STATUS_NAMES=EMPLOYER_STATUS_NAMES,
        ORDER_STATUS_COLORS=services.ORDER_STATUS_COLORS,
        RESPONSE_STATUS_COLORS=services.RESPONSE_STATUS_COLORS,
        EMPLOYER_STATUS_COLORS=services.EMPLOYER_STATUS_COLORS,
        PAYMENT_TYPE_NAMES=services.PAYMENT_TYPE_NAMES,
        PAYMENT_STATUS_NAMES=services.PAYMENT_STATUS_NAMES,
        PAYMENT_STATUS_COLORS=services.PAYMENT_STATUS_COLORS,
        ACTION_NAMES=services.ACTION_NAMES,
        DOCUMENT_TYPES=DOCUMENT_TYPES,
        DOCUMENT_STATUS_NAMES=DOCUMENT_STATUS_NAMES,
        PENALTY_NAMES=PENALTY_NAMES,
        REFERRAL_STATUS_NAMES=REFERRAL_STATUS_NAMES,
    )
    # Счётчики для бейджей в боковом меню
    from flask_login import current_user
    if current_user and current_user.is_authenticated:
        from database.models import Employer, Order, Response, WorkerDocument, Referral
        from config import EmployerStatus, OrderStatus, ResponseStatus
        try:
            ctx["nav_counts"] = {
                "moderation": (
                    db_session.query(Employer).filter(Employer.status == EmployerStatus.PENDING).count()
                    + db_session.query(Order).filter(Order.status.in_(services.MODERATION_STATUSES)).count()
                    + db_session.query(Response).filter(Response.status == ResponseStatus.PENDING).count()
                    + db_session.query(WorkerDocument).filter(WorkerDocument.status == "pending").count()
                ),
                "payments": db_session.query(services.Payment).filter(services.Payment.status == "pending").count(),
                "referrals": db_session.query(Referral).filter(Referral.status == "qualified").count(),
            }
        except Exception:
            logger.exception("Не удалось посчитать счётчики меню")
            ctx["nav_counts"] = {}
    return ctx


# Импорт роутов
from admin.routes import (  # noqa: E402
    main, auth, employers, orders, workers, dashboard,
    moderation, finance, broadcasts, audit, search, reviews, referrals, cities,
)

for _module in (auth, main, dashboard, employers, orders, workers,
                moderation, finance, broadcasts, audit, search, reviews, referrals, cities):
    app.register_blueprint(_module.bp)

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Закрытие сессии после запроса"""
    db_session.remove()
