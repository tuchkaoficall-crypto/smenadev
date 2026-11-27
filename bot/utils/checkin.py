"""
Отметка «📍 Я на месте» в начале смены.

Работник нажимает кнопку (приходит за CHECKIN_PROMPT_MINUTES до начала) и
отправляет геолокацию (или отмечается без неё). Мы сохраняем время, координаты,
опоздание и расстояние до точки заказа (если админ задал точку), уведомляем
работодателя и админов. Опоздание дольше CHECKIN_GRACE_MINUTES даёт штрафной балл.
"""
import logging
import math
from datetime import datetime, timedelta

from sqlalchemy import select, func

from config import (
    OrderStatus, ResponseStatus, CHECKIN_GRACE_MINUTES, CHECKIN_MAX_DISTANCE_M, CHECKIN_PROMPT_MINUTES,
)
from database import async_session
from database.models import Response, ShiftCheckin, AdminAction
from services import order_texts as T
from services import order_keyboards as K
from services import reliability as R

logger = logging.getLogger(__name__)

# Отметиться можно не раньше чем за час до начала и до конца смены
EARLY_WINDOW = timedelta(minutes=max(60, CHECKIN_PROMPT_MINUTES))
CHECKIN_STATUSES = K.RECRUITING + (OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED)


class CheckinError(Exception):
    """Отметиться нельзя: текст можно показать работнику"""


def haversine_m(lat1, lon1, lat2, lon2) -> int:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(a))))


def late_minutes(order, now: datetime) -> int:
    return max(0, int((now - order.shift_date).total_seconds() // 60))


def checkin_summary(name: str, order, c: ShiftCheckin) -> str:
    """Строка для работодателя и админов"""
    parts = [f"📍 <b>{name}</b> на месте · смена #{order.id} · {c.created_at.strftime('%H:%M')}"]
    if c.late_minutes and c.late_minutes > CHECKIN_GRACE_MINUTES:
        parts.append(f"⏰ опоздание {c.late_minutes} мин")
    elif c.late_minutes:
        parts.append(f"(+{c.late_minutes} мин)")
    if c.distance_m is not None:
        far = " ⚠️ далеко от адреса" if c.distance_m > CHECKIN_MAX_DISTANCE_M else ""
        parts.append(f"{c.distance_m} м от точки{far}")
    if c.has_location:
        parts.append(f'<a href="{c.map_url}">карта</a>')
    else:
        parts.append("без геолокации")
    return " · ".join(parts)


async def checkin_count(session, order_id: int) -> int:
    return (await session.execute(
        select(func.count(ShiftCheckin.id)).where(ShiftCheckin.order_id == order_id))).scalar_one()


async def checked_in_worker_ids(session, order_id: int) -> set:
    return set((await session.execute(
        select(ShiftCheckin.worker_id).where(ShiftCheckin.order_id == order_id))).scalars().all())


async def validate(response_id: int, user_id: int, now: datetime = None):
    """Проверить, что отметиться можно. Возвращает отклик (для текста подсказки)"""
    now = now or datetime.now()
    async with async_session() as session:
        response = (await session.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
        if not response or response.worker.user_id != user_id:
            raise CheckinError("Смена не найдена")
        check_allowed(response, now)
        exists = (await session.execute(select(ShiftCheckin.id).where(
            ShiftCheckin.response_id == response_id))).first()
        if exists:
            raise CheckinError("Вы уже отметились на этой смене 👍")
        return response


def check_allowed(response, now):
    order = response.order
    if response.status != ResponseStatus.CONFIRMED or order.status not in CHECKIN_STATUSES:
        raise CheckinError("Эта смена уже неактуальна")
    if now < order.shift_date - EARLY_WINDOW:
        raise CheckinError(f"Отметиться можно не раньше чем за {int(EARLY_WINDOW.total_seconds() // 60)} мин "
                           f"до начала смены ({order.shift_date.strftime('%d.%m %H:%M')})")
    if now > order.shift_date + timedelta(hours=order.shift_duration or 0):
        raise CheckinError("Смена уже закончилась")


async def record_checkin(response_id: int, user_id: int, lat: float = None, lon: float = None,
                         now: datetime = None) -> dict:
    """Сохранить отметку и разослать уведомления. Возвращает детали для ответа работнику"""
    from bot.utils import lifecycle as L

    now = now or datetime.now()
    async with async_session() as session:
        response = (await session.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
        if not response or response.worker.user_id != user_id:
            raise CheckinError("Смена не найдена")
        check_allowed(response, now)
        if (await session.execute(select(ShiftCheckin.id).where(ShiftCheckin.response_id == response_id))).first():
            raise CheckinError("Вы уже отметились на этой смене 👍")

        order, worker = response.order, response.worker
        late = late_minutes(order, now)
        distance = None
        if lat is not None and lon is not None and order.has_point:
            distance = haversine_m(lat, lon, order.latitude, order.longitude)
        c = ShiftCheckin(order_id=order.id, response_id=response.id, worker_id=worker.id, created_at=now,
                         latitude=lat, longitude=lon, distance_m=distance, late_minutes=late)
        session.add(c)
        penalty = None
        if late > CHECKIN_GRACE_MINUTES:
            penalty = R.new_penalty(worker.id, "late_checkin", order_id=order.id,
                                    reason=f"Отметка через {late} мин после начала", actor="бот")
            session.add(penalty)
        name = T.worker_name(worker)
        session.add(AdminAction(admin=f"бот: работник {user_id}", action="checkin", entity_type="order",
                                entity_id=order.id, summary=f"{worker.user.full_name if worker.user else worker.id}: "
                                f"{'геолокация' if lat is not None else 'без геолокации'}, опоздание {late} мин"
                                + (f", {distance} м" if distance is not None else "")))
        await session.commit()
        summary = checkin_summary(name, order, c)
        total_here = await checkin_count(session, order.id)
        confirmed = await L.confirmed_count(session, order.id)
        employer_chat = order.employer.user_id
        points_total = await R.worker_points_async(session, worker.id) if penalty else None
        order_id, address = order.id, order.address

    line = f"{summary}\nНа месте: {total_here} из {confirmed}"
    await L.send(employer_chat, line, K.employer_card_rows(order_id))
    await L.send_admins(line, K.admin_card_rows(order_id))
    if penalty:
        await L.send(user_id, R.penalty_text("late_checkin", penalty.points, points_total, order_id))
    return {"order_id": order_id, "late": late, "distance": distance, "address": address,
            "penalty": penalty.points if penalty else 0}


async def order_checkins_by_response(session, order_id: int) -> dict:
    rows = (await session.execute(select(ShiftCheckin).where(ShiftCheckin.order_id == order_id))).scalars().all()
    return {c.response_id: c for c in rows}
