"""
Форма создания заявки работодателем.

Что умеет:
  • шаги с прогрессом «шаг N из M», подсказками и примерами;
  • «◀️ Назад» и «✖️ Отменить» на каждом шаге;
  • быстрые кнопки (прошлые адреса, даты с днями недели, время, длительность,
    число людей, типичные ставки) и ввод своего значения текстом;
  • проверка ввода с понятными сообщениями (прошедшее время, диапазоны сумм);
  • живой расчёт стоимости и комиссии;
  • итоговая проверка заявки с кнопками «✏️ Изменить» для любого поля;
  • «🔁 Повторить» прошлую заявку: всё подставляется, нужно выбрать только дату.

Формат сохраняемых данных не изменился (OrderService.create_order).
"""
import logging
import re
from datetime import datetime, timedelta, date
from html import escape

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from config import (
    JOB_CATEGORIES, EmployerStatus, calculate_order_cost, PREPAYMENT_PERCENT,
)
from database import async_session
from database.models import Order
from services import EmployerService, OrderService
from services import order_texts as T
from services.cities import active_cities
from bot.keyboards import reply
from bot.keyboards.lifecycle import to_markup
from bot.states import CreateOrder

router = Router()
logger = logging.getLogger(__name__)

# ==== Справочники ====

STEPS = [
    "category", "city", "address", "date", "time", "duration",
    "workers", "payment_type", "payment_amount", "description", "requirements",
]
STEP_STATE = {
    "category": CreateOrder.category,
    "city": CreateOrder.city,
    "address": CreateOrder.address,
    "date": CreateOrder.shift_date,
    "time": CreateOrder.shift_time,
    "duration": CreateOrder.shift_duration,
    "workers": CreateOrder.workers_needed,
    "payment_type": CreateOrder.payment_type,
    "payment_amount": CreateOrder.payment_amount,
    "description": CreateOrder.description,
    "requirements": CreateOrder.requirements,
}
STATE_STEP = {s.state: name for name, s in STEP_STATE.items()}

STEP_TITLES = {
    "category": "Категория",
    "city": "Город",
    "address": "Адрес",
    "date": "Дата",
    "time": "Время начала",
    "duration": "Длительность",
    "workers": "Количество людей",
    "payment_type": "Тип оплаты",
    "payment_amount": "Ставка",
    "description": "Описание",
    "requirements": "Требования",
}

REQUIREMENT_CHIPS = [
    "18+",
    "Медицинская книжка",
    "Паспорт РФ",
    "Опыт работы",
    "Своя спецодежда",
    "Физически выносливый",
    "Без вредных привычек",
]

DESCRIPTION_EXAMPLES = {
    "Грузчик": "Разгрузка фуры с бытовой техникой на склад, коробки до 25 кг. Перчатки выдаём.",
    "Курьер": "Доставка заказов пешком по центру города, 10–15 адресов за смену, термосумка наша.",
    "Промоутер": "Раздача листовок у входа в ТЦ, консультация прохожих об акции магазина.",
    "Официант": "Обслуживание банкета на 60 гостей: подача блюд, уборка столов. Форма: белый верх, чёрный низ.",
    "Уборщик": "Уборка офиса после ремонта, 200 м²: мытьё полов и окон, вынос мусора. Инвентарь наш.",
    "Разнорабочий": "Помощь на стройке: перенос материалов, уборка территории, подсобные работы.",
    "Мерчендайзер": "Выкладка товара на полки в 3 магазинах сети, фотоотчёт в конце смены.",
    "Комплектовщик": "Сборка интернет-заказов на складе по листу подбора, упаковка и маркировка.",
}
DEFAULT_EXAMPLE = "Коротко опишите задачи, условия и что выдаёте на месте."

AMOUNT_PRESETS = {
    "per_hour": [250, 300, 350, 400, 500],
    "per_shift": [1500, 2000, 2500, 3000, 4000],
}
AMOUNT_LIMITS = {"per_hour": (100, 10_000), "per_shift": (300, 100_000)}

NAV_CANCEL = ("✖️ Отменить", "of:cancel")
MAX_DAYS_AHEAD = 90


def single_city() -> bool:
    return len(active_cities()) == 1


def visible_steps():
    return [s for s in STEPS if not (s == "city" and single_city())]


# ==== Отрисовка ====

def _progress(step: str) -> str:
    steps = visible_steps()
    i = steps.index(step) + 1 if step in steps else len(steps)
    n = len(steps)
    return f"📝 <b>Новая заявка</b> · шаг {i} из {n}\n{'▰' * i}{'▱' * (n - i)}\n\n"


def _nav(step: str, data: dict):
    if data.get("editing"):
        return [("↩️ К проверке заявки", "of:summary"), NAV_CANCEL]
    if visible_steps().index(step) == 0:
        return [NAV_CANCEL]
    return [("◀️ Назад", "of:back"), NAV_CANCEL]


def _shift_day(data) -> date | None:
    raw = data.get("shift_day")
    return date.fromisoformat(raw) if raw else None


def cost_block(data: dict) -> str:
    cost = calculate_order_cost(
        data["payment_type"], data["payment_amount"], data["shift_duration"], data["workers_needed"]
    )
    percent = cost["commission_per_worker"] / cost["shift_amount"] * 100 if cost["shift_amount"] else 0
    percent_s = f"{percent:.1f}".rstrip("0").rstrip(".")
    text = (
        f"💵 Работнику: {T.payment_display(data['payment_type'], data['payment_amount'])}"
    )
    if data["payment_type"] == "per_hour":
        text += f" × {data['shift_duration']} ч = {T.rub(cost['shift_amount'])}"
    text += (
        f"\n🧾 Комиссия сервиса: {T.rub(cost['commission_per_worker'])} с человека ({percent_s}%)\n"
        f"👤 Итого за 1 работника: {T.rub(cost['total_per_worker'])}\n"
        f"💰 <b>Всего за {data['workers_needed']} чел.: {T.rub(cost['total_cost'])}</b>\n"
        f"<i>Из них сервису: {T.rub(cost['commission_total'])}, предоплата {PREPAYMENT_PERCENT}% "
        f"от комиссии ({T.rub(cost['prepayment'])}) после набора людей.</i>"
    )
    return text


async def render_step(step: str, data: dict, employer_id: int = None):
    """Вернуть (текст, строки кнопок) для шага"""
    head = _progress(step)
    rows = []

    if step == "category":
        text = head + "👷 <b>Кого вы ищете?</b>\nВыберите категорию работы:"
        buttons = [(("✅ " if data.get("category") == c else "") + c, f"of:cat:{i}")
                   for i, c in enumerate(JOB_CATEGORIES)]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    elif step == "city":
        text = head + "🏙 <b>В каком городе смена?</b>"
        buttons = [(c, f"of:city:{i}") for i, c in enumerate(active_cities())]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    elif step == "address":
        text = head + (
            "📍 <b>Где будет работа?</b>\n"
            "Напишите адрес так, чтобы работник нашёл место без звонка: улица, дом, "
            "при необходимости вход, этаж или ориентир.\n\n"
            "<i>Пример: ул. Ленина, 15, вход со двора, склад №2</i>"
        )
        if data.get("address"):
            text += f"\n\nСейчас: <b>{escape(data['address'])}</b>"
        suggestions = data.get("addr_suggest") or []
        if suggestions:
            text += "\n\nИли выберите адрес из прошлых заявок:"
            rows += [[(f"📍 {a[:48]}", f"of:addr:{i}")] for i, a in enumerate(suggestions)]

    elif step == "date":
        text = head + (
            "📅 <b>Когда смена?</b>\n"
            "Выберите дату или напишите свою, например <code>05.12</code>.\n"
            "<i>Чем раньше опубликована заявка, тем проще найти людей.</i>"
        )
        today = datetime.now().date()
        buttons = []
        for i in range(14):
            d = today + timedelta(days=i)
            label = {0: "Сегодня", 1: "Завтра"}.get(i, T.WEEKDAYS_SHORT[d.weekday()].capitalize())
            mark = "✅ " if data.get("shift_day") == d.isoformat() else ""
            buttons.append((f"{mark}{label}, {d.strftime('%d.%m')}", f"of:date:{d.isoformat()}"))
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    elif step == "time":
        day = _shift_day(data)
        text = head + (
            f"🕐 <b>Во сколько начало смены</b> {T.fmt_date(datetime.combine(day, datetime.min.time()))}?\n"
            "Выберите время или напишите своё, например <code>07:30</code>."
        )
        now = datetime.now()
        buttons = []
        for hour in range(6, 23):
            dt = datetime.combine(day, datetime.min.time()).replace(hour=hour)
            if dt <= now:
                continue
            buttons.append((f"{hour:02d}:00", f"of:time:{hour:02d}00"))
        if not buttons:
            text += "\n\n⚠️ На сегодня стандартное время уже прошло, напишите время вручную или выберите другую дату."
        rows += [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
        prev = data.get("shift_date")
        if prev:
            keep = datetime.combine(day, prev.time())
            if keep > now:
                rows.insert(0, [(f"Оставить {prev.strftime('%H:%M')}", f"of:time:{prev.strftime('%H%M')}")])

    elif step == "duration":
        start = data["shift_date"]
        text = head + (
            f"⏱ <b>Сколько часов длится смена?</b>\n"
            f"Начало: {start.strftime('%d.%m %H:%M')}. Выберите или напишите число от 1 до 24."
        )
        buttons = [(f"{h} ч (до {(start + timedelta(hours=h)).strftime('%H:%M')})", f"of:dur:{h}")
                   for h in (2, 4, 6, 8, 10, 12)]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    elif step == "workers":
        text = head + "👥 <b>Сколько человек нужно?</b>\nВыберите или напишите число от 1 до 100."
        buttons = [(str(n), f"of:wn:{n}") for n in (1, 2, 3, 4, 5, 6, 8, 10, 15, 20)]
        rows += [buttons[:5], buttons[5:]]

    elif step == "payment_type":
        text = head + (
            "💰 <b>Как оплачивается работа?</b>\n"
            "• <b>За смену</b> — фиксированная сумма за всю смену\n"
            "• <b>За час</b> — ставка умножается на длительность смены"
        )
        rows.append([("💰 За смену", "of:pt:per_shift"), ("⏰ За час", "of:pt:per_hour")])

    elif step == "payment_amount":
        pt = data["payment_type"]
        unit = "в час" if pt == "per_hour" else "за смену"
        lo, hi = AMOUNT_LIMITS[pt]
        text = head + (
            f"💵 <b>Сколько получает один работник {unit}?</b>\n"
            "Укажите сумму, которую работник получит на руки. Комиссию сервиса "
            "мы посчитаем отдельно и покажем итог.\n\n"
            f"Выберите или напишите сумму от {T.rub(lo)} до {T.rub(hi)}, например <code>{AMOUNT_PRESETS[pt][2]}</code>."
        )
        rows.append([(T.rub(a), f"of:amt:{a}") for a in AMOUNT_PRESETS[pt]])

    elif step == "description":
        example = DESCRIPTION_EXAMPLES.get(data.get("category"), DEFAULT_EXAMPLE)
        text = head + (
            "📝 <b>Что нужно делать?</b>\n"
            "Опишите задачи и условия, чтобы работник понимал, на что откликается: "
            "что делать, что выдаёте, есть ли перерыв и питание.\n\n"
            f"<i>Пример: {escape(example)}</i>"
        )
        if data.get("payment_amount") and data.get("workers_needed"):
            text += f"\n\n<b>Расчёт стоимости</b>\n{cost_block(data)}"
        if data.get("description"):
            text += f"\n\nСейчас: {escape(data['description'][:300])}"

    elif step == "requirements":
        chips = data.get("req_chips") or []
        text = head + (
            "✅ <b>Есть ли требования к работникам?</b>\n"
            "Отметьте подходящие и при необходимости допишите своё сообщением "
            "(например: «рост от 170 см»). Если требований нет, нажмите «Без требований»."
        )
        if data.get("req_text"):
            text += f"\n\nВаш текст: <i>{escape(data['req_text'])}</i>"
        buttons = [(("✅ " if i in chips else "▫️ ") + c, f"of:req:{i}") for i, c in enumerate(REQUIREMENT_CHIPS)]
        rows += [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        rows.append([("Без требований", "of:reqnone"), ("Готово ➡️", "of:reqdone")])
    else:
        raise ValueError(step)

    rows.append(_nav(step, data))
    return text, rows


def build_requirements(data: dict) -> str | None:
    chips = [REQUIREMENT_CHIPS[i] for i in sorted(data.get("req_chips") or []) if i < len(REQUIREMENT_CHIPS)]
    parts = []
    if chips:
        parts.append(", ".join(chips))
    if data.get("req_text"):
        parts.append(data["req_text"])
    return "; ".join(parts)[:1000] or None


def render_summary(data: dict):
    start = data["shift_date"]
    end = start + timedelta(hours=data["shift_duration"])
    req = build_requirements(data)
    text = (
        "🔎 <b>Проверьте заявку перед отправкой</b>\n\n"
        f"💼 <b>{escape(data['category'])}</b>\n"
        f"📍 {escape(data['city'])}, {escape(data['address'])}\n"
        f"📅 {T.fmt_date(start)}, {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        f"{' (+1 день)' if end.date() != start.date() else ''} · {data['shift_duration']} ч\n"
        f"👥 Нужно: {data['workers_needed']} чел.\n\n"
        f"📝 {escape(data['description'])}\n"
        f"✅ Требования: {escape(req) if req else 'нет'}\n\n"
        f"<b>Стоимость</b>\n{cost_block(data)}\n"
    )
    hours_left = (start - datetime.now()).total_seconds() / 3600
    if hours_left < 6:
        text += "\n⚠️ До начала смены меньше 6 часов. Найти людей так быстро получится не всегда.\n"
    text += "\nЕсли всё верно, отправьте заявку на модерацию. Обычно проверка занимает до часа."

    edit_steps = [s for s in visible_steps() if s != "payment_type"]
    titles = {**STEP_TITLES, "payment_amount": "Оплата"}
    buttons = [(f"✏️ {titles[s]}", f"of:edit:{s}") for s in edit_steps]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([("✅ Отправить на модерацию", "of:submit")])
    rows.append([NAV_CANCEL])
    return text, rows


# ==== Показ шагов ====

async def _show(message: Message, state: FSMContext, text: str, rows, edit: bool):
    """Показать вопрос: отредактировать текущее сообщение или прислать новое.

    У прошлого вопроса убираем кнопки, чтобы не путаться."""
    markup = to_markup(rows)
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            await state.update_data(form_msg=message.message_id)
            return
        except Exception as e:
            if "not modified" in str(e):
                return
    data = await state.get_data()
    old = data.get("form_msg")
    if old:
        try:
            await message.bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=old, reply_markup=None)
        except Exception:
            pass
    sent = await message.answer(text, parse_mode="HTML", reply_markup=markup)
    await state.update_data(form_msg=sent.message_id)


async def ask(step: str, message: Message, state: FSMContext, edit: bool, prefix: str = ""):
    if step == "summary":
        data = await state.get_data()
        text, rows = render_summary(data)
        await state.set_state(CreateOrder.confirmation)
        await state.update_data(editing=True)
    else:
        if step == "city" and single_city():
            await state.update_data(city=active_cities()[0])
            step = "address"
        data = await state.get_data()
        text, rows = await render_step(step, data)
        await state.set_state(STEP_STATE[step])
    await _show(message, state, prefix + text, rows, edit)


async def go_next(current: str, message: Message, state: FSMContext, edit: bool, prefix: str = ""):
    data = await state.get_data()
    if current == "date":
        nxt = "time"
    elif current == "payment_type":
        nxt = "payment_amount"
    elif current == "time" and data.get("editing") and not data.get("shift_duration"):
        nxt = "duration"
    elif data.get("editing"):
        nxt = "summary"
    else:
        steps = visible_steps()
        i = steps.index(current)
        nxt = steps[i + 1] if i + 1 < len(steps) else "summary"
    await ask(nxt, message, state, edit, prefix)


def _ok(text: str) -> str:
    return f"✅ {text}\n\n"


# ==== Старт ====

async def _approved_employer(user_id: int):
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, user_id)
        if not employer:
            return None, "❌ Сначала необходимо пройти регистрацию работодателя: нажмите /start."
        if employer.status != EmployerStatus.APPROVED:
            return None, ("⏳ Ваша анкета ещё на проверке. Создавать заявки можно после одобрения, "
                          "мы пришлём уведомление.")
        orders = await OrderService.get_employer_orders(session, employer.id)
    seen, addresses = set(), []
    for o in orders:
        key = o.address.strip().lower()
        if key not in seen:
            seen.add(key)
            addresses.append(o.address.strip())
        if len(addresses) == 3:
            break
    return employer, addresses


@router.message(F.text == "➕ Создать заявку")
async def start_create_order(message: Message, state: FSMContext):
    employer, extra = await _approved_employer(message.from_user.id)
    if not employer:
        await message.answer(extra)
        return
    await state.clear()
    await state.update_data(addr_suggest=extra, req_chips=[],
                            city=active_cities()[0] if single_city() else None)
    await message.answer(
        "Заполнение займёт 2–3 минуты. На любом шаге можно вернуться назад, "
        "а перед отправкой вы проверите заявку целиком.",
        reply_markup=reply.get_cancel_keyboard(),
    )
    await ask("category", message, state, edit=False)


@router.callback_query(F.data.startswith("eo:repeat:"))
async def repeat_order(callback: CallbackQuery, state: FSMContext):
    """Создать новую заявку по образцу прошлой"""
    order_id = int(callback.data.split(":")[2])
    employer, extra = await _approved_employer(callback.from_user.id)
    if not employer:
        await callback.answer(extra, show_alert=True)
        return
    async with async_session() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not order or order.employer_id != employer.id:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return

    req_chips, req_text = [], []
    for part in re.split(r"[;,]\s*", order.requirements or ""):
        part = part.strip()
        if not part:
            continue
        if part in REQUIREMENT_CHIPS:
            req_chips.append(REQUIREMENT_CHIPS.index(part))
        else:
            req_text.append(part)

    cities = active_cities()
    city = order.city if order.city in cities else cities[0]
    await state.clear()
    await state.update_data(
        addr_suggest=extra, category=order.category, city=city, address=order.address,
        shift_date=order.shift_date, shift_duration=order.shift_duration,
        workers_needed=order.workers_needed, payment_type=order.payment_type,
        payment_amount=order.payment_amount, description=order.description,
        req_chips=req_chips, req_text=", ".join(req_text) or None, editing=True,
    )
    await callback.answer()
    await ask("date", callback.message, state, edit=False,
              prefix=f"🔁 <b>Повторяем заявку #{order_id}.</b> Все поля подставлены, "
                     "выберите новую дату и время, затем проверьте заявку.\n\n")


# ==== Навигация ====

@router.callback_query(F.data == "of:cancel")
async def form_cancel(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    await state.clear()
    try:
        await callback.message.edit_text("✖️ Создание заявки отменено. Данные не сохранены.")
    except Exception:
        pass
    if current:
        await callback.message.answer("👔 Главное меню", reply_markup=reply.get_employer_menu())
    await callback.answer()


@router.callback_query(F.data == "of:back")
async def form_back(callback: CallbackQuery, state: FSMContext):
    current = STATE_STEP.get(await state.get_state())
    if not current:
        await callback.answer("Форма уже закрыта. Нажмите «➕ Создать заявку».", show_alert=True)
        return
    steps = visible_steps()
    i = steps.index(current)
    await callback.answer()
    if i == 0:
        return
    await ask(steps[i - 1], callback.message, state, edit=True)


@router.callback_query(F.data == "of:summary")
async def form_to_summary(callback: CallbackQuery, state: FSMContext):
    if not await state.get_state():
        await callback.answer("Форма уже закрыта", show_alert=True)
        return
    await callback.answer()
    await ask("summary", callback.message, state, edit=True)


@router.callback_query(F.data.startswith("of:edit:"))
async def form_edit(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() != CreateOrder.confirmation.state:
        await callback.answer("Форма уже закрыта", show_alert=True)
        return
    step = callback.data.split(":")[2]
    if step == "payment_amount":
        step = "payment_type"
    if step not in STEP_STATE:
        await callback.answer()
        return
    await state.update_data(editing=True)
    await callback.answer()
    await ask(step, callback.message, state, edit=True)


# ==== Шаги с кнопками ====

@router.callback_query(CreateOrder.category, F.data.startswith("of:cat:"))
async def step_category(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[2])
    if idx >= len(JOB_CATEGORIES):
        await callback.answer()
        return
    await state.update_data(category=JOB_CATEGORIES[idx])
    await callback.answer()
    await go_next("category", callback.message, state, edit=True,
                  prefix=_ok(f"Категория: <b>{JOB_CATEGORIES[idx]}</b>"))


@router.callback_query(CreateOrder.city, F.data.startswith("of:city:"))
async def step_city(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[2])
    cities = active_cities()
    if idx >= len(cities):
        await callback.answer()
        return
    await state.update_data(city=cities[idx])
    await callback.answer()
    await go_next("city", callback.message, state, edit=True, prefix=_ok(f"Город: <b>{escape(cities[idx])}</b>"))


@router.callback_query(CreateOrder.address, F.data.startswith("of:addr:"))
async def step_address_pick(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    suggestions = data.get("addr_suggest") or []
    idx = int(callback.data.split(":")[2])
    if idx >= len(suggestions):
        await callback.answer()
        return
    await state.update_data(address=suggestions[idx])
    await callback.answer()
    await go_next("address", callback.message, state, edit=True,
                  prefix=_ok(f"Адрес: <b>{escape(suggestions[idx])}</b>"))


async def _set_day(day: date, message: Message, state: FSMContext, edit: bool):
    await state.update_data(shift_day=day.isoformat())
    await go_next("date", message, state, edit=edit,
                  prefix=_ok(f"Дата: <b>{T.fmt_date(datetime.combine(day, datetime.min.time()))}</b>"))


@router.callback_query(CreateOrder.shift_date, F.data.startswith("of:date:"))
async def step_date_pick(callback: CallbackQuery, state: FSMContext):
    try:
        day = date.fromisoformat(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer("❌ Не удалось прочитать дату", show_alert=True)
        return
    if day < datetime.now().date():
        await callback.answer("Эта дата уже прошла, выберите другую", show_alert=True)
        return
    await callback.answer()
    await _set_day(day, callback.message, state, edit=True)


async def _set_time(hour: int, minute: int, message: Message, state: FSMContext, edit: bool) -> str | None:
    """Сохранить время. Вернуть текст ошибки или None"""
    data = await state.get_data()
    day = _shift_day(data)
    shift_date = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
    now = datetime.now()
    if shift_date <= now:
        return "Это время уже прошло. Выберите более позднее время или другую дату."
    await state.update_data(shift_date=shift_date)
    note = ""
    if shift_date - now < timedelta(hours=3):
        note = "⚠️ До начала меньше 3 часов: постараемся, но найти людей так быстро получается не всегда.\n\n"
    await go_next("time", message, state, edit=edit,
                  prefix=_ok(f"Начало: <b>{T.fmt_date(shift_date)} в {shift_date.strftime('%H:%M')}</b>") + note)
    return None


@router.callback_query(CreateOrder.shift_time, F.data.startswith("of:time:"))
async def step_time_pick(callback: CallbackQuery, state: FSMContext):
    raw = callback.data.split(":")[2]
    error = await _set_time(int(raw[:2]), int(raw[2:]), callback.message, state, edit=True)
    await callback.answer(error or "", show_alert=bool(error))


@router.callback_query(CreateOrder.shift_duration, F.data.startswith("of:dur:"))
async def step_duration_pick(callback: CallbackQuery, state: FSMContext):
    hours = int(callback.data.split(":")[2])
    await state.update_data(shift_duration=hours)
    await callback.answer()
    await go_next("duration", callback.message, state, edit=True, prefix=_ok(f"Длительность: <b>{hours} ч</b>"))


@router.callback_query(CreateOrder.workers_needed, F.data.startswith("of:wn:"))
async def step_workers_pick(callback: CallbackQuery, state: FSMContext):
    n = int(callback.data.split(":")[2])
    await state.update_data(workers_needed=n)
    await callback.answer()
    await go_next("workers", callback.message, state, edit=True, prefix=_ok(f"Нужно людей: <b>{n}</b>"))


@router.callback_query(CreateOrder.payment_type, F.data.startswith("of:pt:"))
async def step_payment_type(callback: CallbackQuery, state: FSMContext):
    pt = callback.data.split(":")[2]
    if pt not in AMOUNT_LIMITS:
        await callback.answer()
        return
    data = await state.get_data()
    update = {"payment_type": pt}
    if data.get("payment_type") != pt:
        update["payment_amount"] = None  # ставка за час и за смену несравнимы
    await state.update_data(**update)
    await callback.answer()
    await go_next("payment_type", callback.message, state, edit=True,
                  prefix=_ok(f"Оплата: <b>{'за час' if pt == 'per_hour' else 'за смену'}</b>"))


async def _set_amount(amount: float, message: Message, state: FSMContext, edit: bool) -> str | None:
    data = await state.get_data()
    lo, hi = AMOUNT_LIMITS[data["payment_type"]]
    if not lo <= amount <= hi:
        unit = "в час" if data["payment_type"] == "per_hour" else "за смену"
        return f"Укажите сумму {unit} от {T.rub(lo)} до {T.rub(hi)}."
    await state.update_data(payment_amount=round(amount, 2))
    data = await state.get_data()
    prefix = _ok(f"Ставка: <b>{T.payment_display(data['payment_type'], amount)}</b>")
    if data.get("editing"):
        prefix += f"<b>Новый расчёт</b>\n{cost_block(data)}\n\n"
    await go_next("payment_amount", message, state, edit=edit, prefix=prefix)
    return None


@router.callback_query(CreateOrder.payment_amount, F.data.startswith("of:amt:"))
async def step_amount_pick(callback: CallbackQuery, state: FSMContext):
    error = await _set_amount(float(callback.data.split(":")[2]), callback.message, state, edit=True)
    await callback.answer(error or "", show_alert=bool(error))


@router.callback_query(CreateOrder.requirements, F.data.startswith("of:req:"))
async def step_req_toggle(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[2])
    data = await state.get_data()
    chips = list(data.get("req_chips") or [])
    if idx in chips:
        chips.remove(idx)
    elif idx < len(REQUIREMENT_CHIPS):
        chips.append(idx)
    await state.update_data(req_chips=chips)
    await callback.answer()
    await ask("requirements", callback.message, state, edit=True)


@router.callback_query(CreateOrder.requirements, F.data.in_({"of:reqdone", "of:reqnone"}))
async def step_req_done(callback: CallbackQuery, state: FSMContext):
    if callback.data == "of:reqnone":
        await state.update_data(req_chips=[], req_text=None)
    data = await state.get_data()
    req = build_requirements(data)
    await callback.answer()
    await go_next("requirements", callback.message, state, edit=True,
                  prefix=_ok(f"Требования: <b>{escape(req) if req else 'нет'}</b>"))


# ==== Шаги с вводом текста ====

def _text(message: Message) -> str:
    return (message.text or "").strip()


@router.message(CreateOrder.address)
async def step_address_text(message: Message, state: FSMContext):
    address = re.sub(r"\s+", " ", _text(message))
    if len(address) < 5:
        await message.answer("❌ Адрес слишком короткий. Напишите улицу и номер дома, например: "
                             "<i>ул. Ленина, 15</i>", parse_mode="HTML")
        return
    if len(address) > 300:
        await message.answer("❌ Слишком длинно. Оставьте адрес и ориентир (до 300 символов), "
                             "подробности можно указать в описании.")
        return
    await state.update_data(address=address)
    note = "" if re.search(r"\d", address) else "💡 В адресе нет номера дома. Если он есть, его можно добавить позже кнопкой «✏️ Адрес».\n\n"
    await go_next("address", message, state, edit=False, prefix=_ok(f"Адрес: <b>{escape(address)}</b>") + note)


def parse_day(text: str, today: date) -> date | None:
    t = text.lower().strip()
    words = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
    if t in words:
        return today + timedelta(days=words[t])
    m = re.fullmatch(r"(\d{1,2})[.\-/ ](\d{1,2})(?:[.\-/ ](\d{2}|\d{4}))?", t)
    if not m:
        return None
    d, mth = int(m.group(1)), int(m.group(2))
    year = m.group(3)
    try:
        if year:
            y = int(year) + (2000 if len(year) == 2 else 0)
            return date(y, mth, d)
        candidate = date(today.year, mth, d)
        if candidate < today:
            candidate = date(today.year + 1, mth, d)
        return candidate
    except ValueError:
        return None


@router.message(CreateOrder.shift_date)
async def step_date_text(message: Message, state: FSMContext):
    today = datetime.now().date()
    day = parse_day(_text(message), today)
    if not day:
        await message.answer("❌ Не понял дату. Напишите в формате ДД.ММ, например <code>05.12</code>, "
                             "или выберите кнопкой выше.", parse_mode="HTML")
        return
    if day < today:
        await message.answer("❌ Эта дата уже прошла. Укажите сегодняшнюю или будущую дату.")
        return
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        await message.answer(f"❌ Заявку можно создать не более чем на {MAX_DAYS_AHEAD} дней вперёд.")
        return
    await _set_day(day, message, state, edit=False)


def parse_time(text: str):
    t = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?:[:.\-ч]?(\d{2}))?", t)
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2) or 0)
    if 0 <= h <= 23 and 0 <= mnt <= 59:
        return h, mnt
    return None


@router.message(CreateOrder.shift_time)
async def step_time_text(message: Message, state: FSMContext):
    parsed = parse_time(_text(message))
    if not parsed:
        await message.answer("❌ Не понял время. Напишите, например, <code>07:30</code> или <code>9</code>.",
                             parse_mode="HTML")
        return
    error = await _set_time(*parsed, message, state, edit=False)
    if error:
        await message.answer(f"❌ {error}")


@router.message(CreateOrder.shift_duration)
async def step_duration_text(message: Message, state: FSMContext):
    raw = _text(message).lower().replace("ч", "").replace(",", ".").strip()
    try:
        hours = float(raw)
    except ValueError:
        await message.answer("❌ Напишите число часов от 1 до 24, например <code>8</code>.", parse_mode="HTML")
        return
    if hours != int(hours) or not 1 <= hours <= 24:
        await message.answer("❌ Укажите целое число часов от 1 до 24.")
        return
    await state.update_data(shift_duration=int(hours))
    await go_next("duration", message, state, edit=False, prefix=_ok(f"Длительность: <b>{int(hours)} ч</b>"))


@router.message(CreateOrder.workers_needed)
async def step_workers_text(message: Message, state: FSMContext):
    raw = re.sub(r"\D", "", _text(message))
    if not raw or not 1 <= int(raw) <= 100:
        await message.answer("❌ Укажите количество людей числом от 1 до 100.")
        return
    n = int(raw)
    await state.update_data(workers_needed=n)
    await go_next("workers", message, state, edit=False, prefix=_ok(f"Нужно людей: <b>{n}</b>"))


@router.message(CreateOrder.payment_amount)
async def step_amount_text(message: Message, state: FSMContext):
    raw = _text(message).lower().replace(" ", "").replace(" ", "").replace("₽", "") \
        .replace("руб", "").replace("р", "").replace(",", ".")
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("❌ Напишите сумму числом, например <code>2500</code>.", parse_mode="HTML")
        return
    error = await _set_amount(amount, message, state, edit=False)
    if error:
        await message.answer(f"❌ {error}")


@router.message(CreateOrder.description)
async def step_description_text(message: Message, state: FSMContext):
    description = _text(message)
    if len(description) < 15:
        await message.answer("❌ Слишком коротко. Опишите задачи хотя бы одним-двумя предложениями "
                             "(от 15 символов), так отклики будут точнее.")
        return
    if len(description) > 1500:
        await message.answer(f"❌ Описание длиннее 1500 символов ({len(description)}). Сократите, пожалуйста.")
        return
    await state.update_data(description=description)
    await go_next("description", message, state, edit=False, prefix=_ok("Описание сохранено"))


@router.message(CreateOrder.requirements)
async def step_requirements_text(message: Message, state: FSMContext):
    text = _text(message)
    if text.startswith("/skip"):
        await state.update_data(req_chips=[], req_text=None)
        await go_next("requirements", message, state, edit=False, prefix=_ok("Требования: <b>нет</b>"))
        return
    if not text:
        await message.answer("Напишите требования текстом или нажмите «Готово ➡️».")
        return
    await state.update_data(req_text=text[:500])
    await ask("requirements", message, state, edit=False, prefix=_ok("Добавил ваш текст. Нажмите «Готово ➡️», "
                                                                      "когда закончите."))


@router.message(CreateOrder.category)
@router.message(CreateOrder.city)
@router.message(CreateOrder.payment_type)
@router.message(CreateOrder.confirmation)
async def step_buttons_only(message: Message, state: FSMContext):
    """Текст на шаге, где нужен выбор кнопкой"""
    step = STATE_STEP.get(await state.get_state(), "summary")
    await ask(step, message, state, edit=False, prefix="👆 Здесь нужно выбрать вариант кнопкой.\n\n")


# ==== Отправка ====

@router.callback_query(CreateOrder.confirmation, F.data == "of:submit")
async def submit_order(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    required = ("category", "city", "address", "shift_date", "shift_duration", "workers_needed",
                "payment_type", "payment_amount", "description")
    missing = [k for k in required if not data.get(k)]
    if missing:
        step = {"shift_date": "date", "shift_duration": "duration", "workers_needed": "workers"}.get(missing[0], missing[0])
        await callback.answer("Заполните недостающее поле", show_alert=True)
        await ask(step, callback.message, state, edit=True)
        return
    if data["shift_date"] <= datetime.now():
        await callback.answer("Время начала смены уже прошло, выберите новую дату", show_alert=True)
        await ask("date", callback.message, state, edit=True)
        return

    # Сначала сбрасываем состояние: двойное нажатие не создаст вторую заявку
    await state.clear()
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, callback.from_user.id)
        if not employer or employer.status != EmployerStatus.APPROVED:
            await callback.message.edit_text("❌ Ваша анкета не одобрена, создать заявку нельзя.")
            await callback.answer()
            return
        order = await OrderService.create_order(
            session,
            employer_id=employer.id,
            city=data["city"],
            address=data["address"],
            shift_date=data["shift_date"],
            shift_duration=data["shift_duration"],
            workers_needed=data["workers_needed"],
            category=data["category"],
            description=data["description"],
            requirements=build_requirements(data),
            payment_type=data["payment_type"],
            payment_amount=data["payment_amount"],
        )

    try:
        from bot.utils.notifications import notify_admins_new_order
        await notify_admins_new_order(order.id)
    except Exception as e:
        logger.exception("Ошибка уведомления админов о заявке: %s", e)

    await callback.message.edit_text(
        f"✅ <b>Заявка #{order.id} отправлена на модерацию!</b>\n\n"
        f"{T.short_order(order)}\n\n"
        "Что дальше:\n"
        "1. Администратор проверит заявку (обычно до часа)\n"
        "2. Вакансию получат подходящие работники\n"
        "3. О каждом подтверждённом работнике мы сообщим вам\n"
        "4. За сутки до смены пришлём напоминание\n\n"
        "Следить за заявкой можно в «📋 Мои заявки».",
        parse_mode="HTML",
        reply_markup=to_markup([[("📋 Открыть заявку", f"eo:card:{order.id}")]]),
    )
    await callback.message.answer("👔 Главное меню", reply_markup=reply.get_employer_menu())
    await callback.answer("Заявка отправлена")
