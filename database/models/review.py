"""
Модель отзыва о работнике
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Integer, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database.database import Base


class Review(Base):
    """
    Отзыв работодателя о работнике после завершения смены
    """
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    employer_id = Column(Integer, ForeignKey("employers.id"), nullable=False)
    
    # Оценки
    rating = Column(Integer, nullable=False)  # 1-5 звёзд
    punctuality = Column(Integer, nullable=True)  # Пунктуальность 1-5
    responsibility = Column(Integer, nullable=True)  # Ответственность 1-5
    quality = Column(Integer, nullable=True)  # Качество работы 1-5
    communication = Column(Integer, nullable=True)  # Соблюдение договорённостей 1-5
    
    # Текстовый отзыв
    comment = Column(Text, nullable=True)
    
    # Дата создания
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Скрыт ли отзыв администратором
    is_hidden = Column(Boolean, default=False, nullable=False)
    hidden_reason = Column(Text, nullable=True)
    
    # Relationships
    order = relationship("Order", backref="reviews", foreign_keys=[order_id], lazy="selectin")
    worker = relationship("Worker", backref="reviews", foreign_keys=[worker_id], lazy="selectin")
    employer = relationship("Employer", backref="reviews", foreign_keys=[employer_id], lazy="selectin")
    
    def __repr__(self):
        return f"<Review {self.id}: Worker {self.worker_id} - {self.rating}★>"
    
    @property
    def rating_display(self):
        """Отображение рейтинга со звездами"""
        return "★" * self.rating + "☆" * (5 - self.rating)
