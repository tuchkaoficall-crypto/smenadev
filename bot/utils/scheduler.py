"""
Напоминания по сменам. Работает фоновой задачей внутри бота (раз в минуту).

Что отправляется (каждое — один раз, учёт в таблице order_events):
  • за сутки (или как только смена ближе 24 ч): подтверждённым работникам —
    напоминание с кнопками «Буду» / «Не смогу»; работодателю — сводка набора;
    админам — предупреждение о недоборе;
  • за 2 часа: подтверждённым работникам — повторное напоминание с адресом;
  • через 15 минут после начала, если смена не отмечена начавшейся, — админам;
  • смена началась, а людей нет — админам (предложение отменить);
  • после окончания смены — работодателю «Подтвердите завершение», админам карточка;
  • через сутки после завершения — работодателю напоминание оценить работников;
  • за CHECKIN_PROMPT_MINUTES до начала — работникам кнопка «📍 Я на месте»;
  • через CHECKIN_GRACE_MINUTES после начала — работодателю и админам список не отметившихся.
Плюс фоновые задачи: второй этап рассылки вакансий (после приоритетных работников),
начисление реферальных бонусов, обновление списка городов.
Статусы заказа сам планировщик не меняет: шаги делает человек.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from config import (
    OrderStatus, ResponseStatus, CHECKIN_PROMPT_MINUTES, CHECKIN_GRACE_MINUTES, PRIORITY_DELAY_MINUTES,
)
from database import async_session
from database.models import Order, OrderEvent
from services import order_texts as T
from services import order_keyboards as K
from bot.utils import lifecycle as L
from bot.utils import checkin as C
from services import vacancy as V

logger = logging.getLogger(__name__)

WATCHED = (
    OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT,
    OrderStatus.SHIFT_STARTED, OrderStatus.SHIFT_COMPLETED,
)
BEFORE_START = K.RECRUITING + (OrderStatus.PREPAYMENT,)


async def run_reminders(now: datetime = None) -> int:
    """Один проход. Возвращает число отправленных напоминаний (для тестов и логов)"""
    now = now or datetime.now()
    sent = 0
    async with async_session() as session:
        orders = list((await session.execute(
            select(Order).where(
                Order.status.in_(WATCHED),
                Order.shift_date <= now + timedelta(hours=24),
                Order.shift_date >= now - timedelta(days=3),
            )
        )).scalars().all())

        for order in orders:
            try:
                sent += await _process(session, order, now)
            except Exception as e:
                logger.exception("Напоминания по заказу #%s: %s", order.id, e)
    return sent


async def _process(session, order, now) -> int:
    sent = 0
    hours_left = (order.shift_date - now).total_seconds() / 3600
    end = order.shift_date + timedelta(hours=order.shift_duration or 0)
    confirmed = await L.order_responses(session, order.id, (ResponseStatus.CONFIRMED,))
    employer_chat = order.employer.user_id

    if order.status in BEFORE_START and hours_left > 0:
        # За сутки (или сразу, если смена ближе): каждому подтверждённому один раз
        if hours_left > 2:
            for r in confirmed:
                if await L.add_event(session, order.id, "remind_24h", r.worker.user_id):
                    sent += await L.send(r.worker.user_id, T.worker_reminder(order, now),
                                         K.worker_reminder_rows(r.id))
            if await L.add_event(session, order.id, "remind_24h_employer"):
                sent += await L.send(employer_chat, T.employer_reminder(order, len(confirmed), now),
                                     K.employer_card_rows(order.id))
        else:
            if confirmed and await L.add_event(session, order.id, "remind_2h_employer"):
                sent += await L.send(employer_chat, T.employer_reminder_2h(order, len(confirmed), now),
                                     K.employer_card_rows(order.id))
            for r in confirmed:
                if await L.add_event(session, order.id, "remind_2h", r.worker.user_id):
                    attended = await L.has_event(session, order.id, "attend_ok", r.worker.user_id)
                    rows = None if attended else K.worker_reminder_rows(r.id)
                    sent += await L.send(r.worker.user_id, T.worker_reminder(order, now), rows)

        if len(confirmed) < order.workers_needed and await L.add_event(session, order.id, "admin_understaffed"):
            await L.notify_admins_card(
                order.id, f"⚠️ <b>Недобор</b>: до смены {hours_left:.0f} ч, подтверждено "
                          f"{len(confirmed)} из {order.workers_needed}.")
            sent += 1

    # Отметка «я на месте»: кнопка перед началом и сводка тем, кто не отметился
    in_shift = order.status in C.CHECKIN_STATUSES and now < end
    if in_shift and confirmed and hours_left <= CHECKIN_PROMPT_MINUTES / 60:
        here = await C.checked_in_worker_ids(session, order.id)
        for r in confirmed:
            if r.worker_id not in here and await L.add_event(session, order.id, "checkin_prompt", r.worker.user_id):
                sent += await L.send(r.worker.user_id, T.worker_checkin_prompt(order, now),
                                     K.worker_checkin_rows(r.id))
        missing = [T.worker_name(r.worker) for r in confirmed if r.worker_id not in here]
        late = hours_left <= -CHECKIN_GRACE_MINUTES / 60
        if missing and late and await L.add_event(session, order.id, "no_checkin_alert"):
            text = T.no_checkin_alert(order, missing)
            sent += await L.send(employer_chat, text, K.employer_card_rows(order.id))
            await L.notify_admins_card(order.id, text + "\nЕсли работник не пришёл, отметьте неявку "
                                                        "в карточке заказа в веб-панели.")

    # Смена должна была начаться
    if order.status in BEFORE_START and hours_left <= -0.25:
        if confirmed and await L.add_event(session, order.id, "admin_not_started"):
            await L.notify_admins_card(order.id, "⏰ Смена должна была начаться 15 минут назад, "
                                                 "но не отмечена начавшейся.")
            sent += 1
        elif not confirmed and await L.add_event(session, order.id, "admin_nobody"):
            await L.notify_admins_card(order.id, "🚨 Смена уже началась, а подтверждённых работников нет. "
                                                 "Отменить заказ или срочно найти людей?")
            sent += 1

    # Смена должна была закончиться
    active = order.status in BEFORE_START + (OrderStatus.SHIFT_STARTED,)
    if active and confirmed and now >= end:
        if await L.add_event(session, order.id, "ask_complete"):
            sent += await L.send(employer_chat, T.employer_shift_should_be_over(order),
                                 K.employer_done_rows(order.id))
            await L.notify_admins_card(order.id, "🏁 Время смены вышло. Ждём подтверждения завершения "
                                                 "от работодателя или завершите смену сами.")

    # Напомнить оценить работников
    if order.status == OrderStatus.SHIFT_COMPLETED and order.completed_at \
            and datetime.utcnow() - order.completed_at >= timedelta(hours=24):
        if await L.unrated_workers(session, order) and await L.add_event(session, order.id, "remind_rate"):
            sent += await L.send(employer_chat, T.employer_rate_reminder(order),
                                 [[("⭐️ Оценить работников", f"eo:rate:{order.id}")]])
    return sent


async def run_vacancy_rest(now_utc: datetime = None) -> int:
    """Второй этап рассылки: вакансии остальным работникам после приоритетных"""
    from bot.utils.notifications import notify_workers_new_order
    now_utc = now_utc or datetime.utcnow()
    async with async_session() as session:
        started = set((await session.execute(select(OrderEvent.order_id).where(
            OrderEvent.kind == V.EV_PRIORITY, OrderEvent.user_id == 0))).scalars().all())
        finished = set((await session.execute(select(OrderEvent.order_id).where(
            OrderEvent.kind == V.EV_REST, OrderEvent.user_id == 0))).scalars().all())
        pending = started - finished
        if not pending:
            return 0
        orders = list((await session.execute(select(Order).where(
            Order.id.in_(pending), Order.status == OrderStatus.SEARCH_WORKERS))).scalars().all())
        due = [o.id for o in orders
               if (o.moderated_at or now_utc) + timedelta(minutes=PRIORITY_DELAY_MINUTES) <= now_utc]
    total = 0
    for order_id in due:
        try:
            total += await notify_workers_new_order(order_id, stage="rest")
        except Exception as e:
            logger.exception("Второй этап рассылки по заказу #%s: %s", order_id, e)
    return total


async def run_background(now: datetime = None) -> int:
    """Все периодические задачи за один проход (для цикла и тестов)"""
    from services import cities
    from bot.utils import referrals
    async with async_session() as session:
        await cities.refresh_async(session)
    n = await run_reminders(now)
    n += await run_vacancy_rest()
    n += await referrals.run_referrals()
    return n


async def reminder_loop(interval: int = 60):
    logger.info("Планировщик напоминаний запущен (каждые %s с)", interval)
    while True:
        try:
            n = await run_background()
            if n:
                logger.info("Отправлено напоминаний: %s", n)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Ошибка планировщика напоминаний: %s", e)
        await asyncio.sleep(interval)
