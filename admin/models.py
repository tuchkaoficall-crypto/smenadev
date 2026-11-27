"""
Модели для Flask админ-панели
"""
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class AdminUser(UserMixin):
    """Модель администратора для Flask-Login"""
    
    def __init__(self, id, username):
        self.id = id
        self.username = username
    
    @staticmethod
    def verify_login(username, password):
        """Проверка логина и пароля"""
        from config import ADMIN_USERNAME, ADMIN_PASSWORD
        
        import hmac
        if (
            username and password
            and hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
            and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
        ):
            return AdminUser(id=1, username=username)
        return None
