"""
Журнал отправленных по заказу уведомлений и отметок (напоминания, «буду на смене»).

Нужен, чтобы планировщик не слал одно и то же напоминание дважды
(в том числе после перезапуска бота). Таблица только добавляется.
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, DateTime, Integer, UniqueConstraint
from database.database import Base


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (UniqueConstraint("order_id", "kind", "user_id", name="uq_order_event"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(50), nullable=False)    # remind_24h, remind_2h, attend_ok, ...
    user_id = Column(BigInteger, nullable=False, default=0)  # 0 — событие заказа целиком
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<OrderEvent {self.kind} order#{self.order_id} user {self.user_id}>"
