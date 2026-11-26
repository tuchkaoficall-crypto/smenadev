"""
Flask админ-панель для СМЕНА
"""
from flask import Flask
from flask_login import LoginManager
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from config import ADMIN_SECRET_KEY, SYNC_DATABASE_URL

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

# Импорт роутов
from admin.routes import main, auth, employers, orders, workers, dashboard

# Регистрация blueprints
app.register_blueprint(auth.bp)
app.register_blueprint(main.bp)
app.register_blueprint(dashboard.bp)
app.register_blueprint(employers.bp)
app.register_blueprint(orders.bp)
app.register_blueprint(workers.bp)

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Закрытие сессии после запроса"""
    db_session.remove()
