"""
Бизнес-логика админ-панели: жизненный цикл заказа, аудит, рейтинги, CSV, рассылки.

Логика переходов повторяет то, что делает бот (bot/handlers/admin.py),
чтобы заказ можно было вести целиком из веб-панели.
"""
import csv
import io
import json
import logging
import threading
import time
from datetime import datetime

from flask import Response as FlaskResponse
from flask_login import current_user
from sqlalchemy.orm import Session

from admin import db_session, engine
from admin import telegram
from services import order_texts as T
from services import order_keyboards as K
from config import (
    OrderStatus, ResponseStatus, ORDER_STATUS_NAMES, PREPAYMENT_PERCENT,
)
from database.models import (
    Order, Response, Review, Worker, User, Payment, AdminAction, Broadcast,
)

logger = logging.getLogger(__name__)


# ==== Справочники для UI ====

# Основной путь заказа (отмена — отдельная ветка)
PIPELINE = [
    (OrderStatus.CREATED, "Создан", "bi-file-earmark-plus"),
    (OrderStatus.MODERATION, "Модерация", "bi-shield-check"),
    (OrderStatus.SEARCH_WORKERS, "Поиск", "bi-search"),
    (OrderStatus.CONFIRM_WORKERS, "Набор закрыт", "bi-people"),
    (OrderStatus.PREPAYMENT, "Предоплата", "bi-credit-card"),
    (OrderStatus.SHIFT_STARTED, "Смена идёт", "bi-play-circle"),
    (OrderStatus.SHIFT_COMPLETED, "Смена завершена", "bi-flag"),
    (OrderStatus.PAYMENT_COMPLETED, "Расчёт закрыт", "bi-check2-all"),
]
PIPELINE_INDEX = {s: i for i, (s, _, _) in enumerate(PIPELINE)}

ORDER_STATUS_COLORS = {
    OrderStatus.CREATED: "secondary",
    OrderStatus.MODERATION: "warning",
    OrderStatus.SEARCH_WORKERS: "info",
    OrderStatus.CONFIRM_WORKERS: "primary",
    OrderStatus.PREPAYMENT: "orange",
    OrderStatus.SHIFT_STARTED: "purple",
    OrderStatus.SHIFT_COMPLETED: "teal",
    OrderStatus.PAYMENT_COMPLETED: "success",
    OrderStatus.CANCELLED: "danger",
}
RESPONSE_STATUS_COLORS = {
    ResponseStatus.PENDING: "warning",
    ResponseStatus.CONTACTED: "info",
    ResponseStatus.CONFIRMED: "primary",
    ResponseStatus.REJECTED: "danger",
    ResponseStatus.COMPLETED: "success",
    ResponseStatus.WITHDRAWN: "secondary",
    ResponseStatus.NO_SHOW: "dark",
}
EMPLOYER_STATUS_COLORS = {
    "pending": "warning", "approved": "success", "rejected": "danger", "blocked": "dark",
}
PAYMENT_TYPE_NAMES = {"prepayment": "Предоплата", "final_payment": "Окончательный расчёт"}
PAYMENT_STATUS_NAMES = {"pending": "Ожидает", "completed": "Оплачен", "cancelled": "Отменён"}
PAYMENT_STATUS_COLORS = {"pending": "warning", "completed": "success", "cancelled": "secondary"}

MODERATION_STATUSES = (OrderStatus.CREATED, OrderStatus.MODERATION)
ACTIVE_STATUSES = (
    OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS,
    OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED, OrderStatus.SHIFT_COMPLETED,
)
FINAL_STATUSES = (OrderStatus.PAYMENT_COMPLETED, OrderStatus.CANCELLED)

ACTION_NAMES = {
    "order_approve": "Заказ одобрен",
    "order_reject": "Заказ отклонён",
    "order_cancel": "Заказ отменён",
    "order_status": "Статус изменён вручную",
    "order_prepayment": "Запрошена предоплата",
    "order_start": "Смена начата",
    "order_complete": "Смена завершена",
    "order_close": "Расчёт закрыт",
    "response_confirm": "Отклик подтверждён",
    "response_reject": "Отклик отклонён",
    "response_contact": "Связались с работником",
    "payment_paid": "Платёж отмечен оплаченным",
    "payment_cancel": "Платёж отменён",
    "employer_approve": "Работодатель одобрен",
    "employer_reject": "Работодатель отклонён",
    "employer_block": "Работодатель заблокирован",
    "employer_unblock": "Работодатель разблокирован",
    "user_ban": "Пользователь заблокирован",
    "user_unban": "Пользователь разблокирован",
    "review_hide": "Отзыв скрыт",
    "review_unhide": "Отзыв восстановлен",
    "broadcast": "Рассылка",
    "note": "Заметка",
    "login": "Вход в панель",
    "checkin": "Работник на месте",
    "response_no_show": "Неявка на смену",
    "response_withdraw": "Работник отказался",
    "penalty_add": "Начислены штрафные баллы",
    "penalty_cancel": "Штраф аннулирован",
    "document_approve": "Документ подтверждён",
    "document_reject": "Документ отклонён",
    "verification_revoke": "Проверка документов снята",
    "order_point": "Точка на карте",
    "referral_paid": "Реферальный бонус выплачен",
    "referral_rejected": "Реферал отклонён",
    "referral_qualified": "Реферальный бонус начислен",
    "referral_invited": "Реферал возвращён",
    "city_add": "Город добавлен",
    "city_toggle": "Город включён/выключен",
    "city_rename": "Город переименован",
}


def _notify(chat_id, text, rows=None):
    """Уведомление с теми же текстами и кнопками, что и в боте"""
    return telegram.send_message(chat_id, text, K.to_dict(rows) if rows else None, parse_mode="HTML")


class LifecycleError(Exception):
    """Недопустимый переход по жизненному циклу заказа"""


# ==== Аудит ====

def log_action(action, entity_type=None, entity_id=None, summary=None, commit=True):
    admin_name = getattr(current_user, "username", None) if current_user else None
    db_session.add(AdminAction(
        admin=admin_name, action=action, entity_type=entity_type,
        entity_id=entity_id, summary=summary,
    ))
    if commit:
        db_session.commit()


def entity_history(entity_type, entity_id, limit=100):
    return db_session.query(AdminAction).filter(
        AdminAction.entity_type == entity_type, AdminAction.entity_id == entity_id
    ).order_by(AdminAction.created_at.desc()).limit(limit).all()


# ==== Деньги ====

def order_gmv(order):
    """Фонд оплаты работникам по заказу"""
    return (order.shift_amount or 0) * (order.workers_needed or 0)


def prepayment_due(order):
    if order.prepayment_amount:
        return order.prepayment_amount
    return (order.commission or 0) * PREPAYMENT_PERCENT / 100


def paid_total(order):
    return sum(p.amount for p in order.payments if p.status == "completed")


# ==== Отклики ====

def confirmed_count(order):
    return sum(1 for r in order.responses if r.status == ResponseStatus.CONFIRMED)


def confirm_response(response):
    if response.status not in (ResponseStatus.PENDING, ResponseStatus.CONTACTED):
        raise LifecycleError("Отклик уже обработан")
    order = response.order
    if order.status in FINAL_STATUSES:
        raise LifecycleError("Заказ уже закрыт или отменён")
    confirmed = confirmed_count(order)
    if confirmed >= order.workers_needed:
        raise LifecycleError(f"Уже подтверждено {confirmed} из {order.workers_needed}")

    response.status = ResponseStatus.CONFIRMED
    response.confirmed_at = datetime.utcnow()
    confirmed += 1
    filled = confirmed >= order.workers_needed
    if filled and order.status == OrderStatus.SEARCH_WORKERS:
        order.status = OrderStatus.CONFIRM_WORKERS
    log_action("response_confirm", "order", order.id,
               f"{_worker_name(response.worker)} ({confirmed}/{order.workers_needed})", commit=False)
    db_session.commit()

    _notify(response.worker.user_id, T.worker_confirmed(order), K.worker_confirmed_rows(response.id))
    _notify(order.employer.user_id, T.employer_worker_confirmed(order, response.worker, confirmed),
            K.employer_card_rows(order.id))
    return confirmed, filled


def reject_response(response, reason=None):
    if response.status in (ResponseStatus.REJECTED, ResponseStatus.COMPLETED, ResponseStatus.WITHDRAWN):
        raise LifecycleError("Отклик уже обработан")
    was_confirmed = response.status == ResponseStatus.CONFIRMED
    response.status = ResponseStatus.REJECTED
    if reason:
        response.admin_comment = reason
    order = response.order
    # Освободилось место — возвращаем заказ в поиск
    if was_confirmed and order.status == OrderStatus.CONFIRM_WORKERS:
        order.status = OrderStatus.SEARCH_WORKERS
    log_action("response_reject", "order", order.id,
               f"{_worker_name(response.worker)}" + (f": {reason}" if reason else ""), commit=False)
    db_session.commit()
    _notify(response.worker.user_id, T.worker_response_rejected(order, reason))


def contact_response(response):
    if response.status != ResponseStatus.PENDING:
        raise LifecycleError("Отклик уже не в ожидании")
    response.status = ResponseStatus.CONTACTED
    response.contacted_at = datetime.utcnow()
    log_action("response_contact", "order", response.order_id, _worker_name(response.worker), commit=False)
    db_session.commit()


# ==== Переходы заказа ====

def next_actions(order):
    """Какие кнопки «следующего шага» показать на карточке заказа"""
    s = order.status
    actions = []
    if s in MODERATION_STATUSES:
        actions += ["approve", "reject"]
    if s in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS):
        actions.append("prepayment")
    if s in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT):
        actions.append("start")
    if s in (OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED):
        actions.append("complete")
    if s == OrderStatus.SHIFT_COMPLETED:
        actions.append("close")
    if s not in FINAL_STATUSES and s not in MODERATION_STATUSES:
        actions.append("cancel")
    return actions


def approve_order(order):
    if order.status not in MODERATION_STATUSES:
        raise LifecycleError("Заказ уже прошёл модерацию")
    order.status = OrderStatus.SEARCH_WORKERS
    order.moderated_at = datetime.utcnow()
    db_session.commit()
    _notify(order.employer.user_id, T.employer_order_approved(order), K.employer_card_rows(order.id))
    sent = telegram.notify_workers_new_order(db_session, order)
    log_action("order_approve", "order", order.id, f"Разослано работникам: {sent}")
    return sent


def reject_order(order, reason):
    if order.status not in MODERATION_STATUSES:
        raise LifecycleError("Заказ уже прошёл модерацию")
    order.status = OrderStatus.CANCELLED
    order.rejection_reason = reason
    log_action("order_reject", "order", order.id, reason, commit=False)
    db_session.commit()
    _notify(order.employer.user_id, T.employer_order_rejected(order, reason),
            [[("🔁 Исправить и отправить заново", f"eo:repeat:{order.id}")]])


def request_prepayment(order):
    if order.status not in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS):
        raise LifecycleError("Предоплату можно запросить только во время набора")
    amount = round(prepayment_due(order), 2)
    existing = [p for p in order.payments if p.payment_type == "prepayment" and p.status != "cancelled"]
    if not existing:
        db_session.add(Payment(order_id=order.id, payment_type="prepayment", amount=amount,
                               status="pending", comment="Запрошено из админ-панели"))
    order.status = OrderStatus.PREPAYMENT
    order.prepayment_amount = amount
    log_action("order_prepayment", "order", order.id, f"{amount:.0f} ₽", commit=False)
    db_session.commit()
    _notify(order.employer.user_id, T.employer_prepayment(order, amount), K.employer_paid_rows(order.id))
    return amount


def start_shift(order):
    if order.status not in (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT):
        raise LifecycleError("Смену нельзя начать из текущего статуса")
    if confirmed_count(order) == 0:
        raise LifecycleError("Нет подтверждённых работников")
    order.status = OrderStatus.SHIFT_STARTED
    order.started_at = datetime.utcnow()
    workers = [r for r in order.responses if r.status == ResponseStatus.CONFIRMED]
    log_action("order_start", "order", order.id, f"Работников: {len(workers)}", commit=False)
    db_session.commit()
    _notify(order.employer.user_id, T.employer_shift_started(order, len(workers)),
            K.employer_done_rows(order.id)[:1] + K.employer_card_rows(order.id))
    for r in workers:
        _notify(r.worker.user_id, T.worker_shift_started(order))


def complete_shift(order):
    """То же, что /complete в боте: отклики -> completed, +1 смена, запрос оценки"""
    if order.status not in (OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED):
        raise LifecycleError("Смену нельзя завершить из текущего статуса")
    responses = [r for r in order.responses if r.status == ResponseStatus.CONFIRMED]
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
    log_action("order_complete", "order", order.id, f"Работников: {len(responses)}", commit=False)
    db_session.commit()

    employer_id = order.employer.user_id
    _notify(employer_id, T.employer_shift_completed(order))
    for r in responses:
        _notify(employer_id, f"👤 {T.worker_name(r.worker)}\n⭐️ {r.worker.rating_display}",
                K.rate_worker_rows(order.id, r.worker.id))
    for r in responses:
        _notify(r.worker.user_id, T.worker_shift_completed(order))
    return len(responses)


def close_order(order):
    if order.status != OrderStatus.SHIFT_COMPLETED:
        raise LifecycleError("Закрыть расчёт можно только после завершения смены")
    for p in order.payments:
        if p.status == "pending":
            p.status = "completed"
            p.paid_at = datetime.utcnow()
    remaining = round((order.commission or 0) - paid_total(order), 2)
    if remaining > 0:
        db_session.add(Payment(order_id=order.id, payment_type="final_payment", amount=remaining,
                               status="completed", paid_at=datetime.utcnow(),
                               comment="Закрытие расчёта из админ-панели"))
    order.status = OrderStatus.PAYMENT_COMPLETED
    order.closed_at = datetime.utcnow()
    log_action("order_close", "order", order.id, f"Комиссия {order.commission or 0:.0f} ₽", commit=False)
    db_session.commit()
    _notify(order.employer.user_id, T.employer_order_closed(order),
            [[("🔁 Повторить заявку", f"eo:repeat:{order.id}")]])


def cancel_order(order, reason):
    if order.status in FINAL_STATUSES:
        raise LifecycleError("Заказ уже закрыт")
    affected = [r for r in order.responses
                if r.status in (ResponseStatus.CONFIRMED, ResponseStatus.CONTACTED, ResponseStatus.PENDING)]
    order.status = OrderStatus.CANCELLED
    order.rejection_reason = reason
    for p in order.payments:
        if p.status == "pending":
            p.status = "cancelled"
    log_action("order_cancel", "order", order.id, reason, commit=False)
    db_session.commit()
    _notify(order.employer.user_id, T.employer_order_cancelled(order, reason),
            [[("🔁 Создать похожую заявку", f"eo:repeat:{order.id}")]])
    for r in affected:
        _notify(r.worker.user_id, T.worker_order_cancelled(order, reason))


def set_status_manual(order, new_status):
    if new_status not in ORDER_STATUS_NAMES:
        raise LifecycleError("Неверный статус")
    old = order.status
    order.status = new_status
    now = datetime.utcnow()
    if new_status == OrderStatus.SHIFT_STARTED and not order.started_at:
        order.started_at = now
    elif new_status == OrderStatus.SHIFT_COMPLETED and not order.completed_at:
        order.completed_at = now
    elif new_status == OrderStatus.PAYMENT_COMPLETED and not order.closed_at:
        order.closed_at = now
    log_action("order_status", "order", order.id,
               f"{ORDER_STATUS_NAMES.get(old, old)} → {ORDER_STATUS_NAMES[new_status]}", commit=False)
    db_session.commit()


# ==== Рейтинг ====

def recalc_worker_rating(worker):
    """Пересчитать рейтинг по видимым отзывам (после скрытия/восстановления)"""
    reviews = db_session.query(Review).filter(
        Review.worker_id == worker.id, Review.is_hidden.is_(False)
    ).all()
    worker.total_reviews = len(reviews)

    def avg(attr):
        vals = [getattr(r, attr) for r in reviews if getattr(r, attr) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    worker.rating = avg("rating")
    worker.punctuality_rating = avg("punctuality")
    worker.responsibility_rating = avg("responsibility")
    worker.quality_rating = avg("quality")
    worker.communication_rating = avg("communication")


# ==== CSV ====

def csv_response(filename, header, rows):
    """CSV для Excel: UTF-8 с BOM, разделитель «;»"""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    data = "﻿" + buf.getvalue()
    return FlaskResponse(
        data, mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def fmt_dt(value):
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


# ==== Рассылки ====

def broadcast_recipients(session, audience, city=None, category=None):
    """Список Telegram ID получателей (заблокированные исключаются)"""
    from database.models import Employer
    ids = set()
    if audience in ("all", "workers"):
        q = session.query(Worker).join(User, Worker.user_id == User.id).filter(
            (User.is_blocked.is_(False)) | (User.is_blocked.is_(None)))
        if city:
            q = q.filter(Worker.city == city)
        for w in q.all():
            if category:
                try:
                    cats = json.loads(w.categories) if w.categories else []
                except (ValueError, TypeError):
                    cats = []
                if cats and category not in cats:
                    continue
            ids.add(w.user_id)
    if audience in ("all", "employers"):
        q = session.query(Employer).join(User, Employer.user_id == User.id).filter(
            (User.is_blocked.is_(False)) | (User.is_blocked.is_(None)),
            Employer.status == "approved",
        )
        ids.update(e.user_id for e in q.all())
    if audience == "all" and not city and not category:
        # Пользователи, которые нажали /start, но ещё не заполнили анкету
        q = session.query(User).filter((User.is_blocked.is_(False)) | (User.is_blocked.is_(None)))
        ids.update(u.id for u in q.all())
    return sorted(ids)


def run_broadcast_async(broadcast_id, recipients, text):
    """Отправка в фоновом потоке со своей сессией БД (~20 сообщений/с — лимит Telegram)"""
    def worker():
        with Session(engine) as session:
            b = session.get(Broadcast, broadcast_id)
            b.status = "running"
            session.commit()
            sent = failed = 0
            for i, chat_id in enumerate(recipients, 1):
                if telegram.send_message(chat_id, text):
                    sent += 1
                else:
                    failed += 1
                if i % 10 == 0:
                    b.sent, b.failed = sent, failed
                    session.commit()
                time.sleep(0.05)
            b.sent, b.failed = sent, failed
            b.status = "done"
            b.finished_at = datetime.utcnow()
            session.commit()

    t = threading.Thread(target=worker, name=f"broadcast-{broadcast_id}", daemon=True)
    t.start()
    return t


def _worker_name(worker):
    if not worker:
        return "—"
    return worker.user.full_name if worker.user else f"ID {worker.user_id}"


def safe_next(default):
    """Адрес возврата из формы (только относительные пути панели)"""
    from flask import request
    nxt = request.form.get('next') or request.args.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt:
        return nxt
    return default
