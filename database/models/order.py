"""
Модель заказа/заявки на подбор работников
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base


class Order(Base):
    """
    Заявка работодателя на подбор работников
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employer_id = Column(Integer, ForeignKey("employers.id"), nullable=False)
    
    # Информация о работе
    city = Column(String(100), nullable=False)
    address = Column(String(500), nullable=False)
    shift_date = Column(DateTime, nullable=False)
    shift_duration = Column(Integer, nullable=False)  # В часах
    workers_needed = Column(Integer, nullable=False)
    
    # Описание работы
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(Text, nullable=True)
    
    # Оплата
    payment_type = Column(String(50), nullable=False)  # per_shift, per_hour
    payment_amount = Column(Float, nullable=False)
    
    # Комиссия
    commission = Column(Float, default=300.0)
    prepayment_amount = Column(Float, default=0.0)
    
    # Статус
    status = Column(String(50), default="created")
    rejection_reason = Column(Text, nullable=True)
    
    # Даты
    created_at = Column(DateTime, default=datetime.utcnow)
    moderated_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    
    # Relationships
    employer = relationship("Employer", backref="orders", foreign_keys=[employer_id])
    
    def __repr__(self):
        return f"<Order #{self.id}: {self.category} in {self.city} ({self.status})>"
    
    @property
    def payment_display(self):
        """Отображение оплаты"""
        if self.payment_type == "per_shift":
            return f"{self.payment_amount:.0f} ₽ за смену"
        return f"{self.payment_amount:.0f} ₽ в час"
    
    @property
    def total_cost(self):
        """Общая стоимость для работодателя"""
        worker_payment = self.payment_amount * self.workers_needed
        return worker_payment + self.commission
