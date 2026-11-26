"""
Модель отклика работника на заказ
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base


class Response(Base):
    """
    Отклик работника на заявку
    """
    __tablename__ = "responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    
    # Статус отклика
    status = Column(String(50), default="pending")  # pending, contacted, confirmed, rejected, completed
    
    # Комментарий от администратора
    admin_comment = Column(Text, nullable=True)
    
    # Даты
    created_at = Column(DateTime, default=datetime.utcnow)
    contacted_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    order = relationship("Order", backref="responses", foreign_keys=[order_id])
    worker = relationship("Worker", backref="responses", foreign_keys=[worker_id])
    
    def __repr__(self):
        return f"<Response {self.id}: Worker {self.worker_id} -> Order {self.order_id} ({self.status})>"
