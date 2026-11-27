"""
Утилиты для отправки уведомлений
"""
from html import escape
import logging

from database import async_session
from services import EmployerService, OrderService, ResponseService, WorkerService
from services import order_texts as T
from config import ADMIN_IDS, ResponseStatus

logger = logging.getLogger(__name__)


async def notify_admins_new_employer(employer_id: int):
    """Уведомить администраторов о новом работодателе"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_employer_moderation_keyboard

    async with async_session() as session:
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        if not employer:
            return

        text = (
            f"🆕 <b>Новый работодатель на проверке</b>\n\n"
            f"🏢 Компания: {escape(employer.company_name)}\n"
            f"👔 Контактное лицо: {escape(employer.contact_person)}\n"
            f"📞 Телефон: {employer.contact_phone}\n"
        )
        if employer.company_description:
            text += f"📝 Описание: {escape(employer.company_description)}\n"
        if employer.inn:
            text += f"🏦 ИНН: {escape(employer.inn)}\n"
        if employer.contact_email:
            text += f"📧 Email: {escape(employer.contact_email)}\n"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML",
                                   reply_markup=get_employer_moderation_keyboard(employer_id))
        except Exception as e:
            logger.warning("Не удалось отправить уведомление: %s", e)


async def notify_admins_new_order(order_id: int):
    """Уведомить администраторов о новом заказе (карточка с кнопками модерации)"""
    from bot.utils.lifecycle import notify_admins_card
    await notify_admins_card(order_id, "🆕 <b>Новая заявка на модерации</b>")


async def notify_admins_new_response(response_id: int):
    """Уведомить администраторов о новом отклике"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_response_actions_keyboard

    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        if not response:
            return
        order = response.order
        worker = response.worker
        confirmed = await ResponseService.get_confirmed_count(session, order.id)
        from services import reliability as R
        points = await R.worker_points_async(session, worker.id)
        lvl = R.level(points)
        reliability = f"{lvl['emoji']} {lvl['label']}" + (f" ({points} б.)" if points else "")
        if worker.verified_at:
            reliability += " · 🪪 документы проверены"

        text = (
            f"🙋 <b>Новый отклик</b> на {T.short_order(order)}\n"
            f"Набрано: {confirmed} из {order.workers_needed}\n\n"
            f"👤 {T.worker_name(worker)}\n"
            f"📞 {worker.user.phone if worker.user and worker.user.phone else 'телефон не указан'}\n"
            f"⭐️ {worker.rating_display}\n"
            f"✅ Завершено смен: {worker.completed_shifts}\n"
            f"{reliability}"
        )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML",
                                   reply_markup=get_response_actions_keyboard(response_id))
        except Exception as e:
            logger.warning("Не удалось отправить уведомление: %s", e)


async def notify_workers_new_order(order_id: int, stage: str = "first") -> int:
    """Разослать вакансию подходящим работникам (см. services/vacancy.py).

    stage="first" — при одобрении: надёжным сразу (или всем, если приоритетных нет),
    stage="rest" — остальным, запускает планировщик. Возвращает число отправленных.
    """
    from datetime import datetime
    from sqlalchemy import select
    from database.models import Worker, Response, OrderEvent
    from config import OrderStatus
    from services import vacancy as V
    from services import reliability as R
    from bot.utils.lifecycle import send

    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        if not order or order.status != OrderStatus.SEARCH_WORKERS or order.shift_date <= datetime.now():
            return 0
        workers = list((await session.execute(select(Worker).where(Worker.city == order.city))).scalars().all())
        responded = set((await session.execute(
            select(Response.worker_id).where(Response.order_id == order_id))).scalars().all())
        sent_ids = set((await session.execute(select(OrderEvent.user_id).where(
            OrderEvent.order_id == order_id, OrderEvent.kind == V.EV_SENT))).scalars().all())
        done = set((await session.execute(select(OrderEvent.kind).where(
            OrderEvent.order_id == order_id, OrderEvent.kind.in_((V.EV_PRIORITY, V.EV_REST)),
            OrderEvent.user_id == 0))).scalars().all())
        if (stage == "first" and V.EV_PRIORITY in done) or (stage == "rest" and V.EV_REST in done):
            return 0
        points = await R.points_map_async(session, [w.id for w in workers])
        targets, priority_ids, events = V.plan(order, workers, points, responded_worker_ids=responded,
                                               sent_user_ids=sent_ids, stage=stage)
        for kind in events:
            if kind not in done:
                session.add(OrderEvent(order_id=order_id, kind=kind, user_id=0))
        for w in targets:
            session.add(OrderEvent(order_id=order_id, kind=V.EV_SENT, user_id=w.user_id))
        await session.commit()
        messages = [(w.user_id, V.vacancy_text(order, w.id in priority_ids and stage == "first"))
                    for w in targets]

    sent = 0
    for chat_id, text in messages:
        if await send(chat_id, text, V.vacancy_rows(order_id)):
            sent += 1
    return sent


async def notify_employer_shift_completed(order_id: int):
    """Уведомить работодателя о завершении смены с просьбой оценить работников"""
    from bot.utils.lifecycle import send
    from services import order_keyboards as K

    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        if not order:
            return
        responses = [
            r for r in await ResponseService.get_order_responses(session, order_id)
            if r.status in (ResponseStatus.CONFIRMED, ResponseStatus.COMPLETED)
        ]
        chat = order.employer.user_id
        text = T.employer_shift_completed(order)
        workers = [(r.worker.id, T.worker_name(r.worker), r.worker.rating_display) for r in responses]

    await send(chat, text)
    for worker_id, name, rating in workers:
        await send(chat, f"👤 {name}\n⭐️ {rating}", K.rate_worker_rows(order_id, worker_id))
