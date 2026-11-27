"""
Модель работника
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Float, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base


class Worker(Base):
    """
    Профиль работника
    """
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Информация о работнике
    city = Column(String(100), nullable=False)
    categories = Column(Text, nullable=False)  # Храним как JSON строку
    photo_url = Column(String(500), nullable=True)
    
    # Рейтинг и статистика
    rating = Column(Float, default=0.0)
    total_reviews = Column(Integer, default=0)
    completed_shifts = Column(Integer, default=0)
    
    # Оценки по критериям (средние значения)
    punctuality_rating = Column(Float, default=0.0)
    responsibility_rating = Column(Float, default=0.0)
    quality_rating = Column(Float, default=0.0)
    communication_rating = Column(Float, default=0.0)
    
    # Проверка документов: дата подтверждения паспорта администратором (добавлено 27.11.2026)
    verified_at = Column(DateTime, nullable=True)

    # Даты
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="worker_profile", foreign_keys=[user_id], lazy="selectin")
    
    @property
    def is_verified(self):
        return self.verified_at is not None

    def __repr__(self):
        return f"<Worker {self.user_id}: ★{self.rating:.1f} ({self.completed_shifts} shifts)>"
    
    @property
    def rating_display(self):
        """Отображение рейтинга со звездами"""
        if self.total_reviews == 0:
            return "Пока нет оценок"
        stars = "★" * int(round(self.rating))
        empty = "☆" * (5 - int(round(self.rating)))
        return f"{stars}{empty} {self.rating:.1f} ({self.total_reviews} оценок)"
