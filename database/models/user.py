"""
Модель пользователя
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean
from database.database import Base


class User(Base):
    """
    Базовая модель пользователя бота
    """
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram ID
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    role = Column(String(50))  # employer, worker, admin
    is_blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.id}: {self.first_name} ({self.role})>"

    @property
    def full_name(self):
        """Полное имя пользователя"""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or "Без имени"
