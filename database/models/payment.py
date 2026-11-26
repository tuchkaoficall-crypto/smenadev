"""
Модель платежа
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Float, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base


class Payment(Base):
    """
    Платёж (предоплата или окончательный расчёт)
    """
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    
    # Тип платежа
    payment_type = Column(String(50), nullable=False)  # prepayment, final_payment
    
    # Сумма
    amount = Column(Float, nullable=False)
    
    # Статус
    status = Column(String(50), default="pending")  # pending, completed, cancelled
    
    # Информация о транзакции
    transaction_id = Column(String(255), nullable=True)
    payment_method = Column(String(100), nullable=True)
    
    # Комментарий
    comment = Column(Text, nullable=True)
    
    # Даты
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    
    # Relationships
    order = relationship("Order", backref="payments", foreign_keys=[order_id])
    
    def __repr__(self):
        return f"<Payment {self.id}: {self.payment_type} {self.amount}₽ ({self.status})>"
