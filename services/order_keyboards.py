"""
Кнопки по жизненному циклу заказа в виде простых списков (текст, callback_data).

Без зависимости от aiogram, чтобы те же кнопки могла отправлять и веб-админка
через Bot API. В боте их превращает в InlineKeyboardMarkup функция
bot.keyboards.lifecycle.to_markup, в админке — to_dict ниже.

Префиксы callback_data:
  eo:<действие>:<order_id>     — работодатель
  wr:<действие>:<response_id>  — работник
  ao:<действие>:<order_id>     — администратор
"""
from datetime import datetime

from config import OrderStatus, ResponseStatus

MODERATION = (OrderStatus.CREATED, OrderStatus.MODERATION)
RECRUITING = (OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS)
BEFORE_START = MODERATION + RECRUITING + (OrderStatus.PREPAYMENT,)
FINAL = (OrderStatus.PAYMENT_COMPLETED, OrderStatus.CANCELLED)
DONE = (OrderStatus.SHIFT_COMPLETED, OrderStatus.PAYMENT_COMPLETED)

# Работник может отказаться, пока смена не началась
WITHDRAWABLE_RESPONSES = (ResponseStatus.PENDING, ResponseStatus.CONTACTED, ResponseStatus.CONFIRMED)


def to_dict(rows):
    """Формат reply_markup для Bot API"""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def shift_started_by_time(order, now: datetime = None) -> bool:
    now = now or datetime.now()
    return bool(order.shift_date and order.shift_date <= now)


# ==== Работодатель ====

def employer_can_cancel_self(order, confirmed: int) -> bool:
    """Отменить сам — пока никто не подтверждён и смена не началась"""
    return order.status in MODERATION + RECRUITING and confirmed == 0


def employer_can_complete(order, confirmed: int, now: datetime = None) -> bool:
    if confirmed == 0:
        return False
    if order.status == OrderStatus.SHIFT_STARTED:
        return True
    return order.status in RECRUITING + (OrderStatus.PREPAYMENT,) and shift_started_by_time(order, now)


def employer_order_rows(order, *, confirmed: int, responses: int = 0,
                        prepayment_pending: bool = False, unrated: int = 0):
    oid = order.id
    rows = []
    s = order.status

    if s == OrderStatus.PREPAYMENT and prepayment_pending:
        rows.append([("✅ Я оплатил предоплату", f"eo:paid:{oid}")])
    if employer_can_complete(order, confirmed):
        rows.append([("🏁 Смена завершена", f"eo:done:{oid}")])
    if s in DONE and unrated:
        rows.append([(f"⭐️ Оценить работников ({unrated})", f"eo:rate:{oid}")])

    second = []
    if s not in MODERATION and s != OrderStatus.CANCELLED:
        label = "👥 Работники" if s not in RECRUITING else f"👥 Кандидаты ({responses})"
        second.append((label, f"eo:resp:{oid}"))
    second.append(("🔄 Обновить", f"eo:card:{oid}"))
    rows.append(second)

    third = []
    if employer_can_cancel_self(order, confirmed):
        third.append(("🗑 Отменить", f"eo:cancel:{oid}"))
    elif s in BEFORE_START:
        third.append(("✉️ Запросить отмену", f"eo:cancelreq:{oid}"))
    third.append(("🔁 Повторить", f"eo:repeat:{oid}"))
    rows.append(third)
    return rows


def employer_paid_rows(order_id: int):
    return [[("✅ Я оплатил предоплату", f"eo:paid:{order_id}")]]


def employer_done_rows(order_id: int):
    return [[("🏁 Да, смена завершена", f"eo:done:{order_id}")],
            [("📋 Открыть заявку", f"eo:card:{order_id}")]]


def employer_card_rows(order_id: int):
    return [[("📋 Открыть заявку", f"eo:card:{order_id}")]]


def rate_worker_rows(order_id: int, worker_id: int):
    return [[("⭐️ Оценить работника", f"rate_worker:{order_id}:{worker_id}")]]


# ==== Работник ====

def worker_can_withdraw(response, order) -> bool:
    return (response.status in WITHDRAWABLE_RESPONSES
            and order.status in BEFORE_START
            and not shift_started_by_time(order))


def worker_response_rows(response, order, can_checkin: bool = False):
    rows = []
    if can_checkin:
        rows.append([("📍 Я на месте", f"wr:checkin:{response.id}")])
    if worker_can_withdraw(response, order):
        label = "❌ Не смогу выйти" if response.status == ResponseStatus.CONFIRMED else "↩️ Отозвать отклик"
        rows.append([(label, f"wr:withdraw:{response.id}")])
    return rows


def worker_reminder_rows(response_id: int):
    return [[("👍 Буду на смене", f"wr:attend:{response_id}"),
             ("❌ Не смогу", f"wr:withdraw:{response_id}")]]


def worker_checkin_rows(response_id: int):
    return [[("📍 Я на месте", f"wr:checkin:{response_id}")]]


def worker_confirmed_rows(response_id: int):
    return [[("❌ Не смогу выйти", f"wr:withdraw:{response_id}")]]


# ==== Администратор ====

def admin_next_actions(order, confirmed: int):
    """Те же «следующие шаги», что в карточке заказа веб-панели"""
    s = order.status
    actions = []
    if s in MODERATION:
        actions += ["approve", "reject"]
    if s in RECRUITING:
        actions.append("prep")
    if s in RECRUITING + (OrderStatus.PREPAYMENT,) and confirmed:
        actions.append("start")
    if s in (OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED) and confirmed:
        actions.append("complete")
    if s == OrderStatus.SHIFT_COMPLETED:
        actions.append("close")
    if s not in FINAL and s not in MODERATION:
        actions.append("cancel")
    return actions


ADMIN_ACTION_LABELS = {
    "approve": "✅ Одобрить",
    "reject": "❌ Отклонить",
    "prep": "💳 Запросить предоплату",
    "paid": "💰 Предоплата получена",
    "start": "▶️ Смена началась",
    "complete": "🏁 Завершить смену",
    "close": "✅ Закрыть расчёт",
    "cancel": "🗑 Отменить заказ",
}


def admin_order_rows(order, *, confirmed: int, prepayment_pending: bool = False):
    oid = order.id
    actions = admin_next_actions(order, confirmed)
    if prepayment_pending and order.status == OrderStatus.PREPAYMENT:
        actions.insert(0, "paid")
    rows = []
    buttons = [(ADMIN_ACTION_LABELS[a], f"ao:{a}:{oid}") for a in actions]
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])
    rows.append([("👥 Отклики", f"ao:resp:{oid}"), ("🔄 Обновить", f"ao:card:{oid}")])
    return rows


def admin_card_rows(order_id: int):
    return [[("📋 Карточка заказа", f"ao:card:{order_id}")]]
