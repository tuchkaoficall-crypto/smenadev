"""
Служебные модели админ-панели: журнал действий и рассылки.

Таблицы только добавляются (create_all создаёт недостающие),
существующие данные не затрагиваются.
"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer
from database.database import Base


class AdminAction(Base):
    """Запись журнала действий администратора (аудит + заметки + таймлайн заказа)"""
    __tablename__ = "admin_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    admin = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True, index=True)  # order, employer, worker, review, broadcast, payment
    entity_id = Column(Integer, nullable=True, index=True)
    summary = Column(Text, nullable=True)

    def __repr__(self):
        return f"<AdminAction {self.action} {self.entity_type}#{self.entity_id}>"


class Broadcast(Base):
    """Рассылка сообщений пользователям через бота"""
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    admin = Column(String(255), nullable=True)
    audience = Column(String(50), nullable=False)  # all, workers, employers
    filters = Column(Text, nullable=True)  # JSON: city, category
    text = Column(Text, nullable=False)
    total = Column(Integer, default=0)
    sent = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String(50), default="pending")  # pending, running, done, failed

    def __repr__(self):
        return f"<Broadcast #{self.id} {self.audience} {self.status}>"
