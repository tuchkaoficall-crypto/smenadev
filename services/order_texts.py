"""
Тексты уведомлений по жизненному циклу заказа.

Используются и ботом (aiogram, async), и веб-админкой (Flask, sync),
чтобы работодатель, работник и админ получали одинаковые сообщения
независимо от того, где был сделан шаг. Все тексты в HTML,
пользовательский ввод экранируется.
"""
from datetime import datetime
from html import escape

from config import ORDER_STATUS_NAMES, OrderStatus, ADMIN_CONTACT

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

# Путь заказа для «трекера» в карточке (отмена — отдельная ветка)
PIPELINE = [
    (OrderStatus.CREATED, "Модерация"),
    (OrderStatus.SEARCH_WORKERS, "Поиск"),
    (OrderStatus.CONFIRM_WORKERS, "Набор"),
    (OrderStatus.PREPAYMENT, "Предоплата"),
    (OrderStatus.SHIFT_STARTED, "Смена"),
    (OrderStatus.SHIFT_COMPLETED, "Завершена"),
    (OrderStatus.PAYMENT_COMPLETED, "Закрыта"),
]
_PIPELINE_POS = {s: i for i, (s, _) in enumerate(PIPELINE)}
_PIPELINE_POS[OrderStatus.MODERATION] = 0

STATUS_EMOJI = {
    OrderStatus.CREATED: "🕓",
    OrderStatus.MODERATION: "🕓",
    OrderStatus.SEARCH_WORKERS: "🔎",
    OrderStatus.CONFIRM_WORKERS: "👥",
    OrderStatus.PREPAYMENT: "💳",
    OrderStatus.SHIFT_STARTED: "▶️",
    OrderStatus.SHIFT_COMPLETED: "🏁",
    OrderStatus.PAYMENT_COMPLETED: "✅",
    OrderStatus.CANCELLED: "❌",
}


def rub(value) -> str:
    """1234.5 -> «1 235 ₽»"""
    return f"{float(value or 0):,.0f}".replace(",", " ") + " ₽"


def fmt_date(dt: datetime, with_weekday: bool = True) -> str:
    if not dt:
        return "—"
    s = dt.strftime("%d.%m.%Y")
    if with_weekday:
        s += f" ({WEEKDAYS_SHORT[dt.weekday()]})"
    return s


def fmt_shift_time(order) -> str:
    """«28.11.2026 (сб), 09:00–17:00 (8 ч)»"""
    start = order.shift_date
    if not start:
        return "—"
    from datetime import timedelta
    end = start + timedelta(hours=order.shift_duration or 0)
    end_s = end.strftime("%H:%M")
    if end.date() != start.date():
        end_s += f" {end.strftime('%d.%m')}"
    return f"{fmt_date(start)}, {start.strftime('%H:%M')}–{end_s} ({order.shift_duration} ч)"


def payment_display(payment_type: str, amount: float) -> str:
    if payment_type == "per_hour":
        return f"{rub(amount)} в час"
    return f"{rub(amount)} за смену"


def status_line(order) -> str:
    name = ORDER_STATUS_NAMES.get(order.status, order.status)
    return f"{STATUS_EMOJI.get(order.status, '📊')} {name}"


def progress_track(order) -> str:
    """Текстовый трекер: ● Модерация → ● Поиск → ○ Набор …"""
    if order.status == OrderStatus.CANCELLED:
        return "❌ Заявка отменена"
    pos = _PIPELINE_POS.get(order.status, 0)
    parts = []
    for i, (_, title) in enumerate(PIPELINE):
        if i < pos:
            parts.append(f"✓ {title}")
        elif i == pos:
            parts.append(f"<b>● {title}</b>")
        else:
            parts.append(f"○ {title}")
    return " → ".join(parts)


def short_order(order) -> str:
    """Одна строка о заказе: «#12 · Грузчик · 28.11 09:00»"""
    return (
        f"#{order.id} · {escape(order.category)} · "
        f"{order.shift_date.strftime('%d.%m %H:%M') if order.shift_date else ''}"
    )


def order_details(order, *, include_description: bool = True) -> str:
    """Основные поля заказа (без статуса)"""
    text = (
        f"💼 <b>{escape(order.category)}</b>\n"
        f"📍 {escape(order.city)}, {escape(order.address)}\n"
        f"📅 {fmt_shift_time(order)}\n"
        f"👥 Нужно: {order.workers_needed} чел.\n"
        f"💰 {payment_display(order.payment_type, order.payment_amount)}"
    )
    if order.payment_type == "per_hour":
        text += f" (≈ {rub(order.shift_amount)} за смену)"
    if include_description and order.description:
        text += f"\n\n📝 {escape(order.description)}"
    if include_description and order.requirements:
        text += f"\n✅ Требования: {escape(order.requirements)}"
    return text


def worker_name(worker) -> str:
    if not worker:
        return "Работник"
    user = getattr(worker, "user", None)
    return escape(user.full_name) if user else f"ID {worker.user_id}"


# ==== Работодатель ====

def employer_order_approved(order) -> str:
    return (
        f"✅ <b>Заявка #{order.id} одобрена и опубликована</b>\n\n"
        f"{order_details(order, include_description=False)}\n\n"
        "Мы разослали вакансию подходящим работникам. Как только кандидаты будут "
        "подтверждены, вы получите уведомление. Ход набора виден в «📋 Мои заявки»."
    )


def employer_order_rejected(order, reason: str) -> str:
    return (
        f"❌ <b>Заявка #{order.id} не прошла модерацию</b>\n\n"
        f"Причина: {escape(reason or 'не указана')}\n\n"
        "Вы можете исправить данные и создать заявку заново: откройте её в «📋 Мои заявки» "
        "и нажмите «🔁 Повторить», все поля подставятся автоматически.\n"
        f"Вопросы: {ADMIN_CONTACT}"
    )


def employer_worker_confirmed(order, worker, confirmed: int) -> str:
    text = (
        f"👤 <b>На заявку #{order.id} подтверждён работник</b>\n\n"
        f"{worker_name(worker)} · ⭐️ {worker.rating_display}\n"
        f"✅ Выполнено смен: {worker.completed_shifts or 0}\n"
        + ("🪪 Документы проверены\n" if getattr(worker, "verified_at", None) else "")
        + f"\nНабрано: <b>{confirmed} из {order.workers_needed}</b>"
    )
    if confirmed >= order.workers_needed:
        text += "\n\n🎉 Набор закрыт! Все работники найдены."
    return text


def employer_worker_withdrew(order, worker, confirmed: int) -> str:
    return (
        f"⚠️ <b>Работник отказался от смены по заявке #{order.id}</b>\n\n"
        f"{worker_name(worker)} больше не выйдет на смену.\n"
        f"Сейчас подтверждено: {confirmed} из {order.workers_needed}.\n\n"
        "Мы уже ищем замену, вакансия снова открыта для откликов."
    )


def employer_prepayment(order, amount: float) -> str:
    return (
        f"💳 <b>Предоплата по заявке #{order.id}</b>\n\n"
        f"Сумма: <b>{rub(amount)}</b> (часть комиссии сервиса).\n"
        f"Реквизиты пришлёт администратор {ADMIN_CONTACT}.\n\n"
        "После оплаты нажмите «✅ Я оплатил», чтобы мы быстрее проверили платёж."
    )


def employer_payment_confirmed(order, amount: float) -> str:
    return f"✅ Оплата {rub(amount)} по заявке #{order.id} получена. Спасибо!"


def employer_shift_started(order, workers_count: int) -> str:
    return (
        f"▶️ <b>Смена по заявке #{order.id} началась</b>\n\n"
        f"На смене: {workers_count} чел.\n"
        "Когда работа будет выполнена, нажмите «🏁 Смена завершена» в карточке заявки."
    )


def employer_shift_completed(order) -> str:
    return (
        f"🏁 <b>Смена по заявке #{order.id} завершена</b>\n\n"
        "Пожалуйста, оцените работников: это займёт минуту и поможет "
        "нам подбирать для вас лучших исполнителей."
    )


def employer_order_closed(order) -> str:
    return (
        f"✅ <b>Расчёт по заявке #{order.id} закрыт</b>\n\n"
        f"Комиссия сервиса: {rub(order.commission)}.\n"
        "Спасибо, что работаете со СМЕНОЙ! Нужны люди снова? "
        "Нажмите «🔁 Повторить», и заявка заполнится по этому образцу."
    )


def employer_order_cancelled(order, reason: str) -> str:
    return (
        f"❌ <b>Заявка #{order.id} отменена</b>\n\n"
        f"Причина: {escape(reason or 'не указана')}"
    )


# ==== Работник ====

def worker_confirmed(order) -> str:
    return (
        f"🎉 <b>Вы подтверждены на смену #{order.id}!</b>\n\n"
        f"{order_details(order)}\n\n"
        "Мы напомним о смене за сутки и за 2 часа до начала.\n"
        "Если планы изменились, откажитесь заранее в «📝 Мои отклики»: "
        "неявка без предупреждения снижает рейтинг."
    )


def worker_response_rejected(order, reason: str = None) -> str:
    text = f"😔 Ваш отклик на вакансию #{order.id} ({escape(order.category)}) не подтверждён."
    if reason:
        text += f"\nПричина: {escape(reason)}"
    text += "\n\nНе расстраивайтесь, новые вакансии появляются каждый день!"
    return text


def worker_shift_started(order) -> str:
    return (
        f"▶️ Смена #{order.id} началась. Удачной работы!\n"
        f"📍 {escape(order.address)}"
    )


def worker_shift_completed(order) -> str:
    return (
        f"🏁 <b>Смена #{order.id} завершена</b>\n\n"
        f"Спасибо за работу! Смена засчитана в ваш профиль.\n"
        f"💰 Оплата: {payment_display(order.payment_type, order.payment_amount)}. "
        "Расчёт с вами проводит работодатель по условиям вакансии."
    )


def worker_order_cancelled(order, reason: str = None) -> str:
    text = (
        f"❌ <b>Смена #{order.id} отменена</b>\n\n"
        f"💼 {escape(order.category)}, {fmt_shift_time(order)}"
    )
    if reason:
        text += f"\nПричина: {escape(reason)}"
    text += "\n\nПриносим извинения. Посмотрите другие вакансии в «🔍 Найти работу»."
    return text


def worker_got_review(order, rating: int, comment: str = None) -> str:
    text = f"⭐️ Работодатель оценил вашу смену #{order.id}: {'⭐️' * rating}"
    if comment:
        text += f"\n💬 «{escape(comment)}»"
    return text


# ==== Напоминания ====

def when_phrase(order, now: datetime = None) -> str:
    """«сегодня в 09:00» / «завтра в 09:00» / «28.11 в 09:00»"""
    now = now or datetime.now()
    d = order.shift_date
    days = (d.date() - now.date()).days
    day = {0: "сегодня", 1: "завтра"}.get(days, d.strftime("%d.%m"))
    return f"{day} в {d.strftime('%H:%M')}"


def worker_reminder(order, now: datetime = None) -> str:
    return (
        f"⏰ <b>Напоминание: смена {when_phrase(order, now)}</b>\n\n"
        f"{order_details(order, include_description=False)}\n\n"
        "Подтвердите, пожалуйста, что выйдете на смену. Если не получается, "
        "нажмите «Не смогу», чтобы мы успели найти замену."
    )


def employer_reminder(order, confirmed: int, now: datetime = None) -> str:
    text = (
        f"⏰ <b>Смена по заявке #{order.id} {when_phrase(order, now)}</b>\n\n"
        f"{order_details(order, include_description=False)}\n\n"
        f"Подтверждено работников: <b>{confirmed} из {order.workers_needed}</b>"
    )
    if confirmed < order.workers_needed:
        text += "\n⚠️ Набор ещё идёт, мы продолжаем искать людей."
    return text


def employer_reminder_2h(order, confirmed: int, now: datetime = None) -> str:
    text = (
        f"⏰ <b>Смена по заявке #{order.id} {when_phrase(order, now)}</b>\n"
        f"📍 {escape(order.address)}\n"
        f"Подтверждено работников: <b>{confirmed} из {order.workers_needed}</b>\n\n"
        "Когда работники придут, они отметятся кнопкой «📍 Я на месте», "
        "и вы получите уведомление о каждом."
    )
    if confirmed < order.workers_needed:
        text += "\n⚠️ Набор ещё не закрыт, администратор ищет людей."
    return text


def worker_checkin_prompt(order, now: datetime = None) -> str:
    return (
        f"📍 <b>Смена #{order.id} начинается {when_phrase(order, now)}</b>\n"
        f"Адрес: {escape(order.city)}, {escape(order.address)}\n\n"
        "Когда будете на месте, нажмите «📍 Я на месте» и отправьте геолокацию: "
        "работодатель сразу увидит, что вы пришли. Опоздание больше 15 минут "
        "снижает надёжность в профиле."
    )


def no_checkin_alert(order, names: list) -> str:
    return (
        f"⏰ <b>Смена #{order.id}</b>: прошло 15 минут, ещё не отметились на месте "
        f"({len(names)}): " + ", ".join(names)
    )


def employer_shift_should_be_over(order) -> str:
    return (
        f"🏁 Смена по заявке #{order.id} должна была закончиться.\n\n"
        "Если работа выполнена, подтвердите завершение: после этого вы сможете "
        "оценить работников."
    )


def employer_rate_reminder(order) -> str:
    return (
        f"⭐️ Вы ещё не оценили работников по заявке #{order.id}.\n"
        "Оценка займёт минуту и поможет подбирать для вас лучших исполнителей."
    )
