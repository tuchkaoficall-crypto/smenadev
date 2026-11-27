"""
Модели для отметок на смене, надёжности работников, рефералов и городов.

Все таблицы новые (создаются автоматически при запуске бота или админки),
существующие таблицы и данные не меняются.
"""
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, Integer, Float, Boolean, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database.database import Base


class ShiftCheckin(Base):
    """Отметка работника «я на месте» (с геолокацией, если он её отправил)"""
    __tablename__ = "shift_checkins"
    __table_args__ = (UniqueConstraint("response_id", name="uq_checkin_response"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)  # местное время, как shift_date
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    distance_m = Column(Integer, nullable=True)   # до точки заказа, если она задана
    late_minutes = Column(Integer, default=0)

    order = relationship("Order", backref="checkins", foreign_keys=[order_id], lazy="selectin")
    worker = relationship("Worker", backref="checkins", foreign_keys=[worker_id], lazy="selectin")

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def map_url(self):
        if not self.has_location:
            return None
        return f"https://yandex.ru/maps/?pt={self.longitude},{self.latitude}&z=17&l=map"


class WorkerPenalty(Base):
    """Штрафные баллы работника (неявка, поздний отказ, опоздание)"""
    __tablename__ = "worker_penalties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False, index=True)
    order_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(50), nullable=False)    # late_cancel, very_late_cancel, no_show, late_checkin, manual
    points = Column(Integer, nullable=False, default=1)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_by = Column(String(255), nullable=True)
    is_cancelled = Column(Boolean, default=False, nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(String(255), nullable=True)

    worker = relationship("Worker", backref="penalties", foreign_keys=[worker_id], lazy="selectin")

    def __repr__(self):
        return f"<WorkerPenalty {self.kind} +{self.points} worker#{self.worker_id}>"


class WorkerDocument(Base):
    """Документ работника для проверки (файл хранится в Telegram, у нас только file_id)"""
    __tablename__ = "worker_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False, default="passport")  # passport, medbook, other
    file_id = Column(String(255), nullable=False)
    file_kind = Column(String(20), nullable=False, default="photo")   # photo, document
    file_name = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending, approved, rejected
    reject_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(255), nullable=True)

    worker = relationship("Worker", backref="documents", foreign_keys=[worker_id], lazy="selectin")


class Referral(Base):
    """Приглашение по реферальной ссылке: кто пригласил, кого, статус бонуса"""
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, nullable=False, index=True)          # Telegram ID пригласившего
    referred_id = Column(BigInteger, nullable=False, unique=True)         # Telegram ID приглашённого
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default="invited")       # invited, qualified, paid, rejected
    role = Column(String(20), nullable=True)                             # роль приглашённого
    bonus_amount = Column(Float, default=0.0)
    qualified_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)


class City(Base):
    """Город, где работает сервис (список редактируется в админ-панели)"""
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<City {self.name}{'' if self.is_active else ' (off)'}>"
