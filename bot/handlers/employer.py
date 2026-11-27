"""
Обработчики для работодателей: регистрация, «Мои заявки» и жизненный цикл
заявки (карточка, отмена, предоплата, завершение смены, оценка работников).
Форма создания заявки — в bot/handlers/order_form.py.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
from html import escape
import logging

from database import async_session
from services import UserService, EmployerService, OrderService, ResponseService, ReviewService
from services import order_texts as T
from services import order_keyboards as K
from bot.keyboards import reply, inline
from bot.keyboards.lifecycle import to_markup, yes_no
from bot.states import EmployerRegistration, RateWorker
from bot.utils import lifecycle as L
from config import UserRole, EmployerStatus, OrderStatus, ResponseStatus, ADMIN_CONTACT

router = Router()
logger = logging.getLogger(__name__)


# ==== Регистрация работодателя ====

async def start_employer_registration(message: Message, state: FSMContext, user_id: int = None):
    """Начало регистрации работодателя
    
    user_id нужно передавать явно, когда message отправлено ботом
    (например, callback.message): там from_user — это сам бот.
    """
    if user_id is None:
        user_id = message.from_user.id
    
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, user_id)
        
        if employer:
            if employer.status == EmployerStatus.APPROVED:
                await message.answer(
                    "✅ Вы уже зарегистрированы и прошли проверку!",
                    reply_markup=reply.get_employer_menu()
                )
                return
            elif employer.status == EmployerStatus.PENDING:
                await message.answer(
                    "⏳ Ваша анкета на проверке у администратора.\n"
                    "Ожидайте уведомления.",
                    reply_markup=reply.get_employer_menu()
                )
                return
            elif employer.status == EmployerStatus.BLOCKED:
                await message.answer(
                    "🚫 Ваш профиль работодателя заблокирован.\n"
                    "Обратитесь к администратору."
                )
                return
            elif employer.status == EmployerStatus.REJECTED:
                await message.answer(
                    f"❌ Ваша анкета была отклонена.\n"
                    f"Причина: {employer.rejection_reason or 'Не указана'}\n\n"
                    "Вы можете заполнить анкету заново."
                )
    
    await message.answer(
        "📝 <b>Регистрация работодателя</b>\n\n"
        "Введите <b>название вашей компании</b> или ИП:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.company_name)


@router.message(EmployerRegistration.company_name)
async def process_company_name(message: Message, state: FSMContext):
    """Обработка названия компании"""
    company_name = (message.text or "").strip()
    
    if len(company_name) < 2:
        await message.answer("❌ Пожалуйста, введите корректное название компании:")
        return
    
    await state.update_data(company_name=company_name)
    await message.answer(
        f"✅ Компания: <b>{escape(company_name)}</b>\n\n"
        "📝 Опишите деятельность вашей компании или нажмите /skip:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.company_description)


@router.message(EmployerRegistration.company_description)
async def process_company_description(message: Message, state: FSMContext):
    """Обработка описания компании"""
    if message.text and message.text.startswith("/skip"):
        description = None
    else:
        description = message.text.strip() if message.text else None
    
    await state.update_data(company_description=description)
    await message.answer(
        f"✅ Описание: {escape(description) if description else 'Не указано'}\n\n"
        "🏢 Введите <b>ИНН компании</b> или /skip:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.inn)


@router.message(EmployerRegistration.inn)
async def process_inn(message: Message, state: FSMContext):
    """Обработка ИНН"""
    if message.text and message.text.startswith("/skip"):
        inn = None
    else:
        inn = message.text.strip() if message.text else None
    
    await state.update_data(inn=inn)
    await message.answer(
        f"✅ ИНН: {escape(inn) if inn else 'Не указан'}\n\n"
        "👤 Введите <b>ФИО контактного лица</b>:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_person)


@router.message(EmployerRegistration.contact_person)
async def process_contact_person(message: Message, state: FSMContext):
    """Обработка контактного лица"""
    contact_person = (message.text or "").strip()
    
    if len(contact_person) < 2:
        await message.answer("❌ Пожалуйста, введите корректное ФИО:")
        return
    
    await state.update_data(contact_person=contact_person)
    await message.answer(
        f"✅ Контактное лицо: <b>{escape(contact_person)}</b>\n\n"
        "📱 Введите <b>номер телефона</b> в формате:\n"
        "+7 (XXX) XXX-XX-XX или 8XXXXXXXXXX",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_phone)


@router.message(EmployerRegistration.contact_phone)
async def process_contact_phone(message: Message, state: FSMContext):
    """Обработка телефона"""
    import re
    phone = (message.text or "").strip()
    
    phone_digits = re.sub(r'\D', '', phone)
    
    if len(phone_digits) < 10 or len(phone_digits) > 11:
        await message.answer(
            "❌ Неверный формат номера. Пожалуйста, введите номер телефона:\n"
            "Например: +7 (900) 123-45-67 или 89001234567"
        )
        return
    
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    elif not phone_digits.startswith('7'):
        phone_digits = '7' + phone_digits
    
    formatted_phone = f"+{phone_digits}"
    
    await state.update_data(contact_phone=formatted_phone)
    await message.answer(
        f"✅ Телефон: <code>{formatted_phone}</code>\n\n"
        "📧 Введите <b>email</b> или /skip:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_email)


@router.message(EmployerRegistration.contact_email)
async def process_contact_email(message: Message, state: FSMContext):
    """Обработка email и завершение регистрации"""
    if message.text and message.text.startswith("/skip"):
        email = None
    else:
        email = message.text.strip() if message.text else None
    
    data = await state.get_data()
    
    # Сохранение в базу данных
    async with async_session() as session:
        employer = await EmployerService.create_employer(
            session,
            user_id=message.from_user.id,
            company_name=data["company_name"],
            contact_person=data["contact_person"],
            contact_phone=data["contact_phone"],
            company_description=data.get("company_description"),
            inn=data.get("inn"),
            contact_email=email
        )
        
        # Уведомление администраторов
        try:
            from bot.utils.notifications import notify_admins_new_employer
            await notify_admins_new_employer(employer.id)
        except Exception as e:
            logger.exception("Ошибка уведомления админов о работодателе: %s", e)
    
    await state.clear()
    await message.answer(
        "✅ <b>Регистрация завершена!</b>\n\n"
        "Ваша анкета отправлена на проверку администратору.\n"
        "Вы получите уведомление о результатах проверки.",
        parse_mode="HTML"
    )
    
    # Отправляем главное меню
    await message.answer(
        "👔 <b>Главное меню работодателя</b>\n\n"
        "Используйте кнопки ниже для навигации:",
        reply_markup=reply.get_employer_menu(),
        parse_mode="HTML"
    )


# ==== Профиль работодателя ====

@router.message(F.text == "👔 Мой профиль")
async def show_employer_profile(message: Message):
    """Показать профиль работодателя"""
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        if not user or user.role != UserRole.EMPLOYER:
            return
        
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if not employer:
            await message.answer("❌ Профиль не найден. Пройдите регистрацию.")
            return
        
        from config import EMPLOYER_STATUS_NAMES
        status_name = EMPLOYER_STATUS_NAMES.get(employer.status, employer.status)
        
        orders = await OrderService.get_employer_orders(session, employer.id)
        
        text = (
            f"╔══════════════════════╗\n"
            f"    <b>👔 ПРОФИЛЬ РАБОТОДАТЕЛЯ</b>\n"
            f"╚══════════════════════╝\n\n"
            f"<b>🏢 Компания:</b> {escape(employer.company_name)}\n"
            f"<b>👤 Контактное лицо:</b> {escape(employer.contact_person)}\n"
            f"<b>📱 Телефон:</b> <code>{employer.contact_phone}</code>\n"
        )
        
        if employer.contact_email:
            text += f"<b>📧 Email:</b> {escape(employer.contact_email)}\n"
        
        if employer.inn:
            text += f"<b>🏢 ИНН:</b> {escape(employer.inn)}\n"
        
        # Определяем эмодзи статуса
        status_emoji = {
            EmployerStatus.PENDING: "⏳",
            EmployerStatus.APPROVED: "✅",
            EmployerStatus.REJECTED: "❌",
            EmployerStatus.BLOCKED: "🚫"
        }.get(employer.status, "📊")
        
        text += (
            f"\n┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  <b>📊 СТАТИСТИКА</b>       ┃\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
            f"  {status_emoji} Статус: <b>{status_name}</b>\n"
            f"  📋 Создано заявок: <b>{len(orders)}</b>\n"
            f"  📅 На платформе с: <b>{employer.created_at.strftime('%d.%m.%Y')}</b>\n"
        )
        
        # Отправляем с фото
        from pathlib import Path
        from aiogram.types import FSInputFile
        from config import ASSETS_DIR
        
        photo_path = Path(ASSETS_DIR) / "smena_profile_employer_1280x720.png"
        
        # Подпись к фото ограничена 1024 символами — длинный профиль шлём текстом
        if photo_path.exists() and len(text) <= 1024:
            photo = FSInputFile(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML"
            )
        else:
            await message.answer(text, parse_mode="HTML")


# ==== Мои заявки ====

@router.message(F.text == "📋 Мои заявки")
async def show_my_orders(message: Message):
    """Список заявок работодателя кнопками: нажатие открывает карточку"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        if not employer:
            await message.answer("❌ Сначала необходимо пройти регистрацию.")
            return
        orders = await OrderService.get_employer_orders(session, employer.id)
        rows, active, done = [], 0, 0
        for order in orders[:20]:
            confirmed = await L.confirmed_count(session, order.id)
            label = f"{T.STATUS_EMOJI.get(order.status, '📋')} {T.short_order(order)}"
            if order.status in K.RECRUITING + (OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED):
                label += f" · {confirmed}/{order.workers_needed}"
            rows.append([(label, f"eo:open:{order.id}")])
        for order in orders:
            if order.status in K.FINAL:
                done += 1
            else:
                active += 1

    if not orders:
        await message.answer(
            "У вас пока нет заявок.\n\nНажмите «➕ Создать заявку»: это займёт 2–3 минуты.",
            reply_markup=reply.get_employer_menu(),
        )
        return
    await message.answer(
        f"📋 <b>Ваши заявки</b>\nАктивных: {active} · завершённых и отменённых: {done}\n\n"
        "🕓 модерация · 🔎 поиск · 👥 набор закрыт · 💳 предоплата · ▶️ смена идёт · "
        "🏁 смена завершена · ✅ закрыта · ❌ отменена\n\nНажмите на заявку, чтобы открыть её:",
        parse_mode="HTML",
        reply_markup=to_markup(rows),
    )


async def _own_order(session, order_id: int, user_id: int):
    order = await L.get_order(session, order_id)
    if not order or not order.employer or order.employer.user_id != user_id:
        return None
    return order


async def _send_card(callback: CallbackQuery, order_id: int, edit: bool):
    async with async_session() as session:
        order = await _own_order(session, order_id, callback.from_user.id)
        if not order:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        text, rows = await L.employer_card(session, order)
    # Редактируем только саму карточку, уведомления оставляем как есть
    is_card = (callback.message.text or "").startswith(f"📋 Заявка #{order_id}")
    if edit and is_card:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=to_markup(rows))
        except Exception as e:
            if "not modified" not in str(e):
                logger.warning("Не удалось обновить карточку: %s", e)
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=to_markup(rows))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^eo:(open|card):\d+$"))
async def employer_order_card(callback: CallbackQuery):
    _, action, order_id = callback.data.split(":")
    await _send_card(callback, int(order_id), edit=action == "card")


@router.callback_query(F.data.startswith("order_status:"))
async def order_status(callback: CallbackQuery):
    """Старые кнопки из прошлых сообщений"""
    await _send_card(callback, int(callback.data.split(":")[1]), edit=False)


@router.callback_query(F.data.regexp(r"^eo:resp:\d+$"))
@router.callback_query(F.data.startswith("order_responses:"))
async def order_responses(callback: CallbackQuery):
    """Кандидаты и работники по заявке"""
    order_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        order = await _own_order(session, order_id, callback.from_user.id)
        if not order:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        responses = await L.order_responses(session, order_id)
        unrated = {r.worker_id for r in await L.unrated_workers(session, order)} if order.status in K.DONE else set()
        from bot.utils.checkin import order_checkins_by_response
        here = await order_checkins_by_response(session, order_id)

    visible = [r for r in responses if r.status not in (ResponseStatus.REJECTED, ResponseStatus.WITHDRAWN)]
    if not visible:
        await callback.answer("Пока нет откликов. Мы сообщим, как только появятся кандидаты.", show_alert=True)
        return

    order_label = {
        ResponseStatus.PENDING: "🕓 на рассмотрении",
        ResponseStatus.CONTACTED: "📞 администратор связался",
        ResponseStatus.CONFIRMED: "✅ подтверждён",
        ResponseStatus.COMPLETED: "🏁 отработал смену",
        ResponseStatus.NO_SHOW: "🚫 не вышел на смену",
    }
    lines = [f"👥 <b>Заявка #{order_id}: кандидаты и работники</b>\n"]
    for i, r in enumerate(visible, 1):
        w = r.worker
        lines.append(
            f"{i}. {T.worker_name(w)} · ⭐️ {w.rating_display} · смен: {w.completed_shifts or 0}\n"
            f"    {order_label.get(r.status, r.status)}"
            + (f" · 📍 на месте с {here[r.id].created_at.strftime('%H:%M')}" if r.id in here else "")
            + (" · 🪪 документы проверены" if w.verified_at else "")
        )
    lines.append("\nКандидатов проверяет и подтверждает администратор, он же передаст контакты "
                 "подтверждённых работников.")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")

    for r in visible:
        if r.worker_id in unrated:
            await callback.message.answer(
                f"👤 {T.worker_name(r.worker)}", parse_mode="HTML",
                reply_markup=inline.get_rate_worker_keyboard(order_id, r.worker_id))
    await callback.answer()


# ---- Отмена ----

@router.callback_query(F.data.regexp(r"^eo:cancel:\d+$"))
@router.callback_query(F.data.startswith("order_cancel:"))
async def order_cancel(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        order = await _own_order(session, order_id, callback.from_user.id)
        if not order:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        if order.status in K.FINAL:
            await callback.answer("Заявка уже закрыта или отменена", show_alert=True)
            return
        confirmed = await L.confirmed_count(session, order_id)
    if not K.employer_can_cancel_self(order, confirmed):
        await _ask_cancel_request(callback, order_id)
        return
    await callback.message.answer(
        f"🗑 Отменить заявку #{order_id}?\nКандидаты, которые откликнулись, получат уведомление.",
        reply_markup=yes_no("🗑 Да, отменить", f"eo:cancelyes:{order_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^eo:cancelyes:\d+$"))
async def order_cancel_yes(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    try:
        await L.cancel_order(order_id, "Отменена работодателем", f"работодатель {callback.from_user.id}",
                             by_employer_user=callback.from_user.id)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(f"🗑 Заявка #{order_id} отменена.",
                                     reply_markup=to_markup([[("🔁 Создать похожую", f"eo:repeat:{order_id}")]]))
    await callback.answer("Заявка отменена")


CANCEL_REQUEST_REASONS = ["Смена перенесена", "Люди больше не нужны", "Нашли работников сами", "Другая причина"]


async def _ask_cancel_request(callback: CallbackQuery, order_id: int):
    rows = [[(r, f"eo:creq:{order_id}:{i}")] for i, r in enumerate(CANCEL_REQUEST_REASONS)]
    rows.append([("↩️ Не отменять", "noop")])
    await callback.message.answer(
        f"✉️ На заявку #{order_id} уже подтверждены работники, поэтому отмену согласует администратор "
        "и предупредит людей.\nУкажите причину:",
        reply_markup=to_markup(rows),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^eo:cancelreq:\d+$"))
async def order_cancel_request(callback: CallbackQuery):
    await _ask_cancel_request(callback, int(callback.data.split(":")[2]))


@router.callback_query(F.data.regexp(r"^eo:creq:\d+:\d+$"))
async def order_cancel_request_reason(callback: CallbackQuery):
    _, _, order_id, idx = callback.data.split(":")
    reason = CANCEL_REQUEST_REASONS[int(idx)] if int(idx) < len(CANCEL_REQUEST_REASONS) else "Другая причина"
    try:
        await L.employer_request_cancel(int(order_id), callback.from_user.id, reason)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(
        f"✉️ Запрос на отмену заявки #{order_id} отправлен администратору. "
        f"Он свяжется с вами в ближайшее время. Вопросы: {ADMIN_CONTACT}")
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Хорошо, ничего не меняем")


# ---- Оплата и завершение ----

@router.callback_query(F.data.regexp(r"^eo:paid:\d+$"))
async def order_paid(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    try:
        await L.employer_reports_paid(order_id, callback.from_user.id)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.answer("Спасибо! Администратор проверит поступление и подтвердит оплату.", show_alert=True)


@router.callback_query(F.data.regexp(r"^eo:done:\d+$"))
async def order_done(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        order = await _own_order(session, order_id, callback.from_user.id)
        if not order:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        confirmed = await L.confirmed_count(session, order_id)
    if order.status in K.DONE:
        await callback.answer("Смена уже отмечена завершённой", show_alert=True)
        return
    if not K.employer_can_complete(order, confirmed):
        await callback.answer("Завершить смену можно после её начала, когда на неё подтверждены работники.",
                              show_alert=True)
        return
    await callback.message.answer(
        f"🏁 Подтвердите, что смена по заявке #{order_id} выполнена ({confirmed} чел.).\n"
        "После этого вы сможете оценить работников.",
        reply_markup=yes_no("🏁 Да, смена выполнена", f"eo:doneyes:{order_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^eo:doneyes:\d+$"))
async def order_done_yes(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    try:
        await L.complete_shift(order_id, f"работодатель {callback.from_user.id}",
                               by_employer_user=callback.from_user.id)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Смена завершена, спасибо!")


@router.callback_query(F.data.regexp(r"^eo:rate:\d+$"))
async def order_rate_list(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        order = await _own_order(session, order_id, callback.from_user.id)
        if not order:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        unrated = await L.unrated_workers(session, order)
    if not unrated:
        await callback.answer("Вы уже оценили всех работников, спасибо!", show_alert=True)
        return
    await callback.answer()
    for r in unrated:
        await callback.message.answer(
            f"👤 {T.worker_name(r.worker)}\n⭐️ {r.worker.rating_display}", parse_mode="HTML",
            reply_markup=inline.get_rate_worker_keyboard(order_id, r.worker_id))


# ==== Оценка работников ====

CRITERIA = [
    ("punctuality", "⏰ Пунктуальность"),
    ("responsibility", "💪 Ответственность"),
    ("quality", "🛠 Качество"),
    ("communication", "🤝 Договорённости"),
]


async def _can_rate(session, order_id: int, worker_id: int, user_id: int):
    """Проверка, что работодатель может оценить работника. Возвращает (order, error)"""
    order = await _own_order(session, order_id, user_id)
    if not order:
        return None, "❌ Заявка не найдена"
    if order.status not in K.DONE:
        return None, "Оценить работника можно после завершения смены"
    response = await ResponseService.get_response_by_worker_and_order(session, worker_id, order_id)
    if not response or response.status not in (ResponseStatus.CONFIRMED, ResponseStatus.COMPLETED):
        return None, "❌ Этот работник не работал на вашей смене"
    if not await ReviewService.can_review(session, order_id, worker_id, order.employer_id):
        return None, "Вы уже оценили этого работника за эту смену"
    return order, None


@router.callback_query(F.data.startswith("rate_worker:"))
async def rate_worker_start(callback: CallbackQuery, state: FSMContext):
    _, order_id, worker_id = callback.data.split(":")
    order_id, worker_id = int(order_id), int(worker_id)
    async with async_session() as session:
        order, error = await _can_rate(session, order_id, worker_id, callback.from_user.id)
        name = None
        if not error:
            response = await ResponseService.get_response_by_worker_and_order(session, worker_id, order_id)
            name = T.worker_name(response.worker)
    if error:
        await callback.answer(error, show_alert=True)
        return
    await callback.message.answer(
        f"⭐️ <b>Общая оценка: {name}</b>\nКак работник справился со сменой #{order_id}?",
        parse_mode="HTML",
        reply_markup=inline.get_rating_stars_keyboard(order_id, worker_id),
    )
    await callback.answer()


def _criteria_markup(crit: dict):
    rows = []
    for key, title in CRITERIA:
        rows.append([(title, "ratec:hint")])
        rows.append([(f"•{n}•" if crit.get(key) == n else str(n), f"ratec:{key}:{n}") for n in range(1, 6)])
    rows.append([("Пропустить", "ratec:next"), ("Далее ➡️", "ratec:next")])
    return to_markup(rows)


@router.callback_query(F.data.startswith("rate:"))
async def rate_worker_value(callback: CallbackQuery, state: FSMContext):
    """Выбрана общая оценка: предлагаем оценить по критериям (необязательно)"""
    _, order_id, worker_id, rating = callback.data.split(":")
    order_id, worker_id, rating = int(order_id), int(worker_id), int(rating)
    if not 1 <= rating <= 5:
        await callback.answer("❌ Неверная оценка", show_alert=True)
        return
    await state.set_state(RateWorker.rating)
    await state.update_data(rate_order_id=order_id, rate_worker_id=worker_id, rate_value=rating, rate_crit={})
    await callback.message.edit_text(
        f"Общая оценка: {'⭐️' * rating}\n\n"
        "Уточните по критериям (по желанию), это помогает точнее подбирать людей:",
        reply_markup=_criteria_markup({}),
    )
    await callback.answer()


@router.callback_query(RateWorker.rating, F.data.startswith("ratec:"))
async def rate_worker_criteria(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if parts[1] == "hint":
        await callback.answer("Выберите оценку от 1 до 5 в строке ниже")
        return
    data = await state.get_data()
    if parts[1] == "next":
        await state.set_state(RateWorker.comment)
        crit = data.get("rate_crit") or {}
        crit_text = "\n".join(f"{title}: {crit[key]}" for key, title in CRITERIA if key in crit)
        await callback.message.edit_text(
            f"Общая оценка: {'⭐️' * data['rate_value']}\n{crit_text}\n\n"
            "💬 Напишите пару слов о работнике или нажмите кнопку ниже:",
            reply_markup=inline.get_skip_comment_keyboard(),
        )
        await callback.answer()
        return
    key, n = parts[1], int(parts[2])
    crit = dict(data.get("rate_crit") or {})
    crit[key] = n
    await state.update_data(rate_crit=crit)
    try:
        await callback.message.edit_reply_markup(reply_markup=_criteria_markup(crit))
    except Exception:
        pass
    await callback.answer()


async def _save_review(user_id: int, state: FSMContext, comment: str = None):
    """Сохранить отзыв. Вернуть (текст ответа, следующий неоценённый или None)"""
    data = await state.get_data()
    await state.clear()
    order_id = data.get("rate_order_id")
    worker_id = data.get("rate_worker_id")
    rating = data.get("rate_value")
    crit = data.get("rate_crit") or {}
    if not order_id or not worker_id or not rating:
        return "❌ Не удалось сохранить оценку. Попробуйте снова.", None

    async with async_session() as session:
        order, error = await _can_rate(session, order_id, worker_id, user_id)
        if error:
            return error, None
        await ReviewService.create_review(
            session, order_id=order_id, worker_id=worker_id, employer_id=order.employer_id,
            rating=rating, comment=comment,
            punctuality=crit.get("punctuality"), responsibility=crit.get("responsibility"),
            quality=crit.get("quality"), communication=crit.get("communication"),
        )
        left = await L.unrated_workers(session, order)
        nxt = (order_id, left[0].worker_id, T.worker_name(left[0].worker)) if left else None

    await L.notify_worker_review(order_id, worker_id, rating, comment)
    text = "✅ Спасибо! Оценка сохранена."
    if not nxt:
        text += " Все работники по этой смене оценены."
    return text, nxt


async def _after_review(target: Message, text: str, nxt):
    if nxt:
        order_id, worker_id, name = nxt
        await target.answer(f"{text}\n\nСледующий: {name}", parse_mode="HTML",
                            reply_markup=inline.get_rate_worker_keyboard(order_id, worker_id))
    else:
        await target.answer(text, reply_markup=reply.get_employer_menu())


@router.callback_query(RateWorker.comment, F.data == "rate_skip_comment")
async def rate_worker_skip_comment(callback: CallbackQuery, state: FSMContext):
    text, nxt = await _save_review(callback.from_user.id, state)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _after_review(callback.message, text, nxt)
    await callback.answer()


@router.message(RateWorker.comment)
async def rate_worker_comment(message: Message, state: FSMContext):
    comment = (message.text or "").strip()[:1000] or None
    text, nxt = await _save_review(message.from_user.id, state, comment)
    await _after_review(message, text, nxt)
