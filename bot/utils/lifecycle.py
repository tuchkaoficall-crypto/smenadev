"""
Жизненный цикл заказа в боте.

Переходы и проверки совпадают с веб-админкой (admin/services.py), тексты
уведомлений общие (services/order_texts.py). Каждое действие:
  1) проверяет, что переход допустим (иначе LifecycleError с понятным текстом),
  2) меняет статусы в БД и пишет запись в журнал admin_actions
     (видна в истории заказа в веб-панели),
  3) после commit рассылает уведомления всем участникам.

Каждая функция открывает свою сессию, поэтому её можно вызывать из любого
обработчика или планировщика.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

from config import ADMIN_IDS, OrderStatus, ResponseStatus, PREPAYMENT_PERCENT, ORDER_STATUS_NAMES
from database import async_session
from database.models import Order, Response, Payment, Review, AdminAction, Worker, OrderEvent
from services import order_texts as T
from services import order_keyboards as K
from services import reliability as R
from bot.keyboards.lifecycle import to_markup

logger = logging.getLogger(__name__)


class LifecycleError(Exception):
    """Недопустимый переход: текст исключения можно показать пользователю"""


# ==== Отправка ====

async def send(chat_id: int, text: str, rows=None) -> bool:
    from bot.bot_instance import bot
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML",
                               reply_markup=to_markup(rows), disable_web_page_preview=True)
        return True
    except Exception as e:
        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
        return False


async def send_admins(text: str, rows=None):
    for admin_id in ADMIN_IDS:
        await send(admin_id, text, rows)


# ==== Чтение ====

async def get_order(session, order_id: int) -> Order | None:
    return (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()


async def order_responses(session, order_id: int, statuses=None):
    q = select(Response).where(Response.order_id == order_id).order_by(Response.created_at)
    if statuses:
        q = q.where(Response.status.in_(statuses))
    return list((await session.execute(q)).scalars().all())


async def confirmed_count(session, order_id: int) -> int:
    return (await session.execute(
        select(func.count(Response.id)).where(
            Response.order_id == order_id, Response.status == ResponseStatus.CONFIRMED)
    )).scalar_one()


async def order_payments(session, order_id: int):
    return list((await session.execute(
        select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)
    )).scalars().all())


async def unrated_workers(session, order) -> list:
    """Отработавшие смену работники, которых работодатель ещё не оценил"""
    done = await order_responses(session, order.id, (ResponseStatus.COMPLETED, ResponseStatus.CONFIRMED))
    rated = set((await session.execute(
        select(Review.worker_id).where(Review.order_id == order.id, Review.employer_id == order.employer_id)
    )).scalars().all())
    return [r for r in done if r.worker_id not in rated]


async def has_event(session, order_id: int, kind: str, user_id: int = 0) -> bool:
    return (await session.execute(select(OrderEvent.id).where(
        OrderEvent.order_id == order_id, OrderEvent.kind == kind, OrderEvent.user_id == user_id
    ))).first() is not None


async def add_event(session, order_id: int, kind: str, user_id: int = 0) -> bool:
    """Записать событие один раз. True — если записали впервые"""
    if await has_event(session, order_id, kind, user_id):
        return False
    session.add(OrderEvent(order_id=order_id, kind=kind, user_id=user_id))
    await session.commit()
    return True


def _log(session, actor: str, action: str, order_id: int, summary: str = None):
    session.add(AdminAction(admin=f"бот: {actor}", action=action, entity_type="order",
                            entity_id=order_id, summary=summary))


# ==== Карточки ====

async def employer_card(session, order):
    confirmed = await confirmed_count(session, order.id)
    responses = await order_responses(session, order.id)
    active_resp = [r for r in responses if r.status in (ResponseStatus.PENDING, ResponseStatus.CONTACTED,
                                                        ResponseStatus.CONFIRMED)]
    payments = await order_payments(session, order.id)
    prep_pending = any(p.payment_type == "prepayment" and p.status == "pending" for p in payments)
    unrated = len(await unrated_workers(session, order)) if order.status in K.DONE else 0

    workers_pay = order.shift_amount * order.workers_needed
    text = (
        f"📋 <b>Заявка #{order.id}</b> · {T.status_line(order)}\n"
        f"{T.progress_track(order)}\n\n"
        f"{T.order_details(order, include_description=False)}\n"
    )
    if order.status not in K.MODERATION and order.status != OrderStatus.CANCELLED:
        text += f"\n👥 Подтверждено: <b>{confirmed} из {order.workers_needed}</b>"
        if order.status in K.RECRUITING:
            text += f" · откликов: {len(active_resp)}"
        if confirmed and order.status in K.BEFORE_START + (OrderStatus.SHIFT_STARTED,) \
                and datetime.now() >= order.shift_date - timedelta(hours=1):
            from bot.utils.checkin import checkin_count
            text += f"\n📍 На месте: <b>{await checkin_count(session, order.id)} из {confirmed}</b>"
        text += "\n"
    text += (
        f"\n💵 Оплата работникам: {T.rub(workers_pay)}\n"
        f"🧾 Комиссия сервиса: {T.rub(order.commission)}\n"
    )
    for p in payments:
        if p.status == "cancelled":
            continue
        kind = "Предоплата" if p.payment_type == "prepayment" else "Расчёт"
        state = "✅ оплачено" if p.status == "completed" else "⏳ ожидает оплаты"
        text += f"💳 {kind}: {T.rub(p.amount)}, {state}\n"
    if order.status == OrderStatus.CANCELLED and order.rejection_reason:
        text += f"\nПричина отмены: {T.escape(order.rejection_reason)}\n"
    if order.status in K.MODERATION:
        text += "\n🕓 Заявка на проверке у администратора, обычно это занимает до часа."
    rows = K.employer_order_rows(order, confirmed=confirmed, responses=len(active_resp),
                                 prepayment_pending=prep_pending, unrated=unrated)
    return text, rows


async def admin_card(session, order):
    confirmed = await confirmed_count(session, order.id)
    responses = await order_responses(session, order.id)
    payments = await order_payments(session, order.id)
    prep_pending = any(p.payment_type == "prepayment" and p.status == "pending" for p in payments)
    counts = {}
    for r in responses:
        counts[r.status] = counts.get(r.status, 0) + 1
    attend = (await session.execute(select(func.count(OrderEvent.id)).where(
        OrderEvent.order_id == order.id, OrderEvent.kind == "attend_ok"))).scalar_one()

    emp = order.employer
    text = (
        f"🛠 <b>Заказ #{order.id}</b> · {T.status_line(order)}\n"
        f"🏢 {T.escape(emp.company_name)} · {T.escape(emp.contact_person)} · {emp.contact_phone}\n\n"
        f"{T.order_details(order)}\n\n"
        f"👥 Подтверждено: <b>{confirmed}/{order.workers_needed}</b>"
        f" · ожидают: {counts.get(ResponseStatus.PENDING, 0) + counts.get(ResponseStatus.CONTACTED, 0)}"
        f" · отказались: {counts.get(ResponseStatus.WITHDRAWN, 0)}"
    )
    if confirmed:
        from bot.utils.checkin import checkin_count
        text += f" · «буду на смене»: {attend} · 📍 на месте: {await checkin_count(session, order.id)}"
    text += f"\n🧾 Комиссия: {T.rub(order.commission)} (предоплата {T.rub(order.prepayment_amount)})"
    for p in payments:
        if p.status != "cancelled":
            kind = "Предоплата" if p.payment_type == "prepayment" else "Расчёт"
            text += f"\n💳 {kind}: {T.rub(p.amount)} — {'оплачено' if p.status == 'completed' else 'ожидает'}"
    if order.rejection_reason and order.status == OrderStatus.CANCELLED:
        text += f"\nПричина отмены: {T.escape(order.rejection_reason)}"
    return text, K.admin_order_rows(order, confirmed=confirmed, prepayment_pending=prep_pending)


def worker_response_card(response, order, can_checkin: bool = False):
    from config import RESPONSE_STATUS_NAMES
    r_status = RESPONSE_STATUS_NAMES.get(response.status, response.status)
    text = (
        f"📌 <b>Вакансия #{order.id}</b>\n"
        f"{T.order_details(order, include_description=False)}\n\n"
        f"📊 Ваш отклик: <b>{r_status}</b>"
    )
    if order.status == OrderStatus.CANCELLED:
        text += "\n❌ Заказ отменён"
    elif response.status == ResponseStatus.CONFIRMED and order.status in K.BEFORE_START:
        text += "\n🎉 Вы в команде! Ждём вас на смене."
    elif response.status in (ResponseStatus.PENDING, ResponseStatus.CONTACTED) and order.status not in K.RECRUITING:
        text += f"\nНабор закрыт ({ORDER_STATUS_NAMES.get(order.status, order.status)})"
    if response.admin_comment and response.status in (ResponseStatus.REJECTED, ResponseStatus.WITHDRAWN):
        text += f"\n💬 {T.escape(response.admin_comment)}"
    return text, K.worker_response_rows(response, order, can_checkin)


async def notify_admins_card(order_id: int, header: str):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            return
        text, rows = await admin_card(session, order)
    await send_admins(f"{header}\n\n{text}", rows)


async def send_employer_card(order_id: int, header: str = None):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            return
        text, rows = await employer_card(session, order)
        chat_id = order.employer.user_id
    await send(chat_id, f"{header}\n\n{text}" if header else text, rows)


# ==== Переходы: модерация ====

async def approve_order(order_id: int, actor: str) -> int:
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if order.status not in K.MODERATION:
            raise LifecycleError("Заказ уже прошёл модерацию")
        order.status = OrderStatus.SEARCH_WORKERS
        order.moderated_at = datetime.utcnow()
        _log(session, actor, "order_approve", order.id)
        await session.commit()
        employer_chat = order.employer.user_id
        text = T.employer_order_approved(order)

    await send(employer_chat, text, K.employer_card_rows(order_id))
    from bot.utils.notifications import notify_workers_new_order
    try:
        return await notify_workers_new_order(order_id)
    except Exception as e:
        logger.exception("Ошибка рассылки вакансии: %s", e)
        return 0


async def reject_order(order_id: int, reason: str, actor: str):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if order.status not in K.MODERATION:
            raise LifecycleError("Заказ уже прошёл модерацию")
        order.status = OrderStatus.CANCELLED
        order.rejection_reason = reason
        _log(session, actor, "order_reject", order.id, reason)
        await session.commit()
        chat = order.employer.user_id
        text = T.employer_order_rejected(order, reason)
    await send(chat, text, [[("🔁 Исправить и отправить заново", f"eo:repeat:{order_id}")]])


# ==== Отклики ====

async def confirm_response(response_id: int, actor: str):
    """Возвращает (confirmed, needed, filled)"""
    async with async_session() as session:
        response = (await session.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
        if not response:
            raise LifecycleError("Отклик не найден")
        if response.status not in (ResponseStatus.PENDING, ResponseStatus.CONTACTED):
            raise LifecycleError("Отклик уже обработан")
        order = response.order
        if order.status not in K.RECRUITING + (OrderStatus.PREPAYMENT,):
            raise LifecycleError("По этому заказу набор уже не идёт")
        confirmed = await confirmed_count(session, order.id)
        if confirmed >= order.workers_needed:
            raise LifecycleError(f"Уже подтверждено {confirmed} из {order.workers_needed}")

        response.status = ResponseStatus.CONFIRMED
        response.confirmed_at = datetime.utcnow()
        confirmed += 1
        filled = confirmed >= order.workers_needed
        if filled and order.status == OrderStatus.SEARCH_WORKERS:
            order.status = OrderStatus.CONFIRM_WORKERS
        worker = response.worker
        _log(session, actor, "response_confirm", order.id,
             f"{worker.user.full_name if worker.user else worker.id} ({confirmed}/{order.workers_needed})")
        await session.commit()
        worker_chat, employer_chat = worker.user_id, order.employer.user_id
        w_text = T.worker_confirmed(order)
        e_text = T.employer_worker_confirmed(order, worker, confirmed)
        needed = order.workers_needed

    await send(worker_chat, w_text, K.worker_confirmed_rows(response_id))
    await send(employer_chat, e_text, K.employer_card_rows(order.id))
    return confirmed, needed, filled


async def reject_response(response_id: int, reason: str, actor: str):
    async with async_session() as session:
        response = (await session.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
        if not response:
            raise LifecycleError("Отклик не найден")
        if response.status in (ResponseStatus.REJECTED, ResponseStatus.COMPLETED, ResponseStatus.WITHDRAWN):
            raise LifecycleError("Отклик уже обработан")
        was_confirmed = response.status == ResponseStatus.CONFIRMED
        response.status = ResponseStatus.REJECTED
        response.admin_comment = reason
        order = response.order
        if was_confirmed and order.status == OrderStatus.CONFIRM_WORKERS:
            order.status = OrderStatus.SEARCH_WORKERS
        _log(session, actor, "response_reject", order.id, reason)
        await session.commit()
        chat = response.worker.user_id
        text = T.worker_response_rejected(order, reason)
    await send(chat, text)


async def withdraw_response(response_id: int, worker_user_id: int):
    """Работник сам отказывается от отклика или подтверждённой смены"""
    async with async_session() as session:
        response = (await session.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
        if not response or response.worker.user_id != worker_user_id:
            raise LifecycleError("Отклик не найден")
        order = response.order
        if not K.worker_can_withdraw(response, order):
            raise LifecycleError("От этой смены уже нельзя отказаться в боте. "
                                 "Срочно напишите администратору.")
        was_confirmed = response.status == ResponseStatus.CONFIRMED
        response.status = ResponseStatus.WITHDRAWN
        response.admin_comment = "Работник отказался сам"
        reopened = False
        if was_confirmed and order.status == OrderStatus.CONFIRM_WORKERS:
            order.status = OrderStatus.SEARCH_WORKERS
            reopened = True
        worker = response.worker
        hours_left = (order.shift_date - datetime.now()).total_seconds() / 3600
        penalty = R.penalty_for_withdraw(hours_left) if was_confirmed else None
        if penalty:
            kind, points = penalty
            session.add(R.new_penalty(worker.id, kind, order_id=order.id, points=points, actor="бот",
                                      reason=f"Отказ за {max(hours_left, 0):.1f} ч до начала"))
        _log(session, f"работник {worker_user_id}", "response_withdraw", order.id,
             f"{worker.user.full_name if worker.user else worker.id}"
             + (" (был подтверждён)" if was_confirmed else "")
             + (f", штраф +{penalty[1]} б." if penalty else ""))
        await session.commit()
        confirmed = await confirmed_count(session, order.id)
        employer_chat = order.employer.user_id
        e_text = T.employer_worker_withdrew(order, worker, confirmed)
        total_points = await R.worker_points_async(session, worker.id) if penalty else 0

    if penalty:
        await send(worker_user_id, R.penalty_text(penalty[0], penalty[1], total_points, order.id))
    if was_confirmed:
        await send(employer_chat, e_text, K.employer_card_rows(order.id))
        urgent = "🚨 СРОЧНО: " if hours_left < 24 else ""
        await notify_admins_card(
            order.id,
            f"{urgent}⚠️ Подтверждённый работник {T.worker_name(worker)} отказался от смены "
            f"(до начала {max(hours_left, 0):.0f} ч). Нужна замена."
            + (" Заказ вернулся в поиск." if reopened else ""),
        )
    return was_confirmed


# ==== Переходы: оплата и смена ====

async def request_prepayment(order_id: int, actor: str) -> float:
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if order.status not in K.RECRUITING:
            raise LifecycleError("Предоплату можно запросить только во время набора")
        amount = round(order.prepayment_amount or (order.commission or 0) * PREPAYMENT_PERCENT / 100, 2)
        payments = await order_payments(session, order.id)
        if not any(p.payment_type == "prepayment" and p.status != "cancelled" for p in payments):
            session.add(Payment(order_id=order.id, payment_type="prepayment", amount=amount,
                                status="pending", comment="Запрошено в боте"))
        order.status = OrderStatus.PREPAYMENT
        order.prepayment_amount = amount
        _log(session, actor, "order_prepayment", order.id, f"{amount:.0f} ₽")
        await session.commit()
        chat = order.employer.user_id
        text = T.employer_prepayment(order, amount)
    await send(chat, text, K.employer_paid_rows(order_id))
    return amount


async def employer_reports_paid(order_id: int, employer_user_id: int):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order or order.employer.user_id != employer_user_id:
            raise LifecycleError("Заявка не найдена")
        payments = [p for p in await order_payments(session, order.id)
                    if p.payment_type == "prepayment" and p.status == "pending"]
        if not payments:
            raise LifecycleError("Ожидающих оплаты платежей нет")
        if not await add_event(session, order.id, "employer_paid", employer_user_id):
            raise LifecycleError("Мы уже получили ваше сообщение об оплате и проверяем платёж")
        amount = payments[0].amount
    await notify_admins_card(order_id, f"💳 Работодатель сообщает, что оплатил предоплату {T.rub(amount)} "
                                       f"по заказу #{order_id}. Проверьте поступление.")


async def mark_prepayment_paid(order_id: int, actor: str) -> float:
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        pending = [p for p in await order_payments(session, order.id)
                   if p.payment_type == "prepayment" and p.status == "pending"]
        if not pending:
            raise LifecycleError("Нет ожидающей предоплаты")
        total = 0
        for p in pending:
            p.status = "completed"
            p.paid_at = datetime.utcnow()
            total += p.amount
        _log(session, actor, "payment_paid", order.id, f"Предоплата {total:.0f} ₽")
        await session.commit()
        chat = order.employer.user_id
        text = T.employer_payment_confirmed(order, total)
    await send(chat, text, K.employer_card_rows(order_id))
    return total


async def start_shift(order_id: int, actor: str) -> int:
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if order.status not in K.RECRUITING + (OrderStatus.PREPAYMENT,):
            raise LifecycleError("Смену нельзя начать из текущего статуса")
        workers = await order_responses(session, order.id, (ResponseStatus.CONFIRMED,))
        if not workers:
            raise LifecycleError("Нет подтверждённых работников")
        order.status = OrderStatus.SHIFT_STARTED
        order.started_at = datetime.utcnow()
        _log(session, actor, "order_start", order.id, f"Работников: {len(workers)}")
        await session.commit()
        employer_chat = order.employer.user_id
        e_text = T.employer_shift_started(order, len(workers))
        w_text = T.worker_shift_started(order)
        worker_chats = [r.worker.user_id for r in workers]
    await send(employer_chat, e_text, K.employer_done_rows(order_id)[:1] + K.employer_card_rows(order_id))
    for chat in worker_chats:
        await send(chat, w_text)
    return len(worker_chats)


async def complete_shift(order_id: int, actor: str, by_employer_user: int = None) -> int:
    """Как /complete и «Завершить смену» в панели: отклики -> completed, +1 смена, запрос оценки"""
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if by_employer_user is not None and order.employer.user_id != by_employer_user:
            raise LifecycleError("Заявка не найдена")
        if order.status in K.DONE:
            raise LifecycleError("Смена уже отмечена завершённой")
        if order.status not in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS,
                                OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED):
            raise LifecycleError("Смену нельзя завершить из текущего статуса")
        responses = await order_responses(session, order.id, (ResponseStatus.CONFIRMED,))
        if not responses:
            raise LifecycleError("Нет подтверждённых работников")
        now = datetime.utcnow()
        for r in responses:
            r.status = ResponseStatus.COMPLETED
            r.completed_at = now
            r.worker.completed_shifts = (r.worker.completed_shifts or 0) + 1
        order.status = OrderStatus.SHIFT_COMPLETED
        order.completed_at = now
        if not order.started_at:
            order.started_at = now
        _log(session, actor, "order_complete", order.id, f"Работников: {len(responses)}")
        await session.commit()
        employer_chat = order.employer.user_id
        e_text = T.employer_shift_completed(order)
        w_text = T.worker_shift_completed(order)
        workers = [(r.worker.id, r.worker.user_id, T.worker_name(r.worker), r.worker.rating_display)
                   for r in responses]

    await send(employer_chat, e_text)
    for worker_id, _, name, rating in workers:
        await send(employer_chat, f"👤 {name}\n⭐️ {rating}", K.rate_worker_rows(order_id, worker_id))
    for _, chat, _, _ in workers:
        await send(chat, w_text)
    if by_employer_user is not None:
        await notify_admins_card(order_id, f"🏁 Работодатель подтвердил завершение смены #{order_id}. "
                                           "Можно закрывать расчёт.")
    return len(workers)


async def close_order(order_id: int, actor: str):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if order.status != OrderStatus.SHIFT_COMPLETED:
            raise LifecycleError("Закрыть расчёт можно только после завершения смены")
        payments = await order_payments(session, order.id)
        now = datetime.utcnow()
        for p in payments:
            if p.status == "pending":
                p.status = "completed"
                p.paid_at = now
        paid = sum(p.amount for p in payments if p.status == "completed")
        remaining = round((order.commission or 0) - paid, 2)
        if remaining > 0:
            session.add(Payment(order_id=order.id, payment_type="final_payment", amount=remaining,
                                status="completed", paid_at=now, comment="Закрытие расчёта в боте"))
        order.status = OrderStatus.PAYMENT_COMPLETED
        order.closed_at = now
        _log(session, actor, "order_close", order.id, f"Комиссия {order.commission or 0:.0f} ₽")
        await session.commit()
        chat = order.employer.user_id
        text = T.employer_order_closed(order)
    await send(chat, text, [[("🔁 Повторить заявку", f"eo:repeat:{order_id}")]])


async def cancel_order(order_id: int, reason: str, actor: str, by_employer_user: int = None):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order:
            raise LifecycleError("Заказ не найден")
        if by_employer_user is not None:
            if order.employer.user_id != by_employer_user:
                raise LifecycleError("Заявка не найдена")
            if not K.employer_can_cancel_self(order, await confirmed_count(session, order.id)):
                raise LifecycleError("На заявку уже подтверждены работники, отменить её можно "
                                     "только через администратора: нажмите «✉️ Запросить отмену».")
        if order.status in K.FINAL:
            raise LifecycleError("Заказ уже закрыт или отменён")
        if order.status in (OrderStatus.SHIFT_STARTED, OrderStatus.SHIFT_COMPLETED) and by_employer_user:
            raise LifecycleError("Смена уже началась")
        affected = await order_responses(session, order.id, (ResponseStatus.CONFIRMED, ResponseStatus.CONTACTED,
                                                             ResponseStatus.PENDING))
        order.status = OrderStatus.CANCELLED
        order.rejection_reason = reason
        for p in await order_payments(session, order.id):
            if p.status == "pending":
                p.status = "cancelled"
        _log(session, actor, "order_cancel", order.id, reason)
        await session.commit()
        employer_chat = order.employer.user_id
        e_text = T.employer_order_cancelled(order, reason)
        w_text = T.worker_order_cancelled(order, reason)
        worker_chats = [r.worker.user_id for r in affected]

    if by_employer_user is None:
        await send(employer_chat, e_text, [[("🔁 Создать похожую заявку", f"eo:repeat:{order_id}")]])
    else:
        await send_admins(f"🗑 Работодатель отменил заявку #{order_id}. Причина: {T.escape(reason)}",
                          K.admin_card_rows(order_id))
    for chat in worker_chats:
        await send(chat, w_text)


async def employer_request_cancel(order_id: int, employer_user_id: int, reason: str):
    async with async_session() as session:
        order = await get_order(session, order_id)
        if not order or order.employer.user_id != employer_user_id:
            raise LifecycleError("Заявка не найдена")
        if order.status not in K.BEFORE_START:
            raise LifecycleError("Смена уже началась или заявка закрыта")
        _log(session, f"работодатель {employer_user_id}", "note", order.id, f"Запрос на отмену: {reason}")
        await session.commit()
    await notify_admins_card(order_id, f"✉️ Работодатель просит отменить заказ #{order_id}.\n"
                                       f"Причина: {T.escape(reason)}")


async def notify_worker_review(order_id: int, worker_id: int, rating: int, comment: str = None):
    async with async_session() as session:
        order = await get_order(session, order_id)
        worker = (await session.execute(select(Worker).where(Worker.id == worker_id))).scalar_one_or_none()
        if not order or not worker:
            return
        text = T.worker_got_review(order, rating, comment)
        chat = worker.user_id
    await send(chat, text)
