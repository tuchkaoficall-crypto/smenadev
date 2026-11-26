"""
Обработчики для работодателей
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import logging

from database import async_session
from services import UserService, EmployerService, OrderService, ResponseService
from bot.keyboards import reply, inline
from bot.states import EmployerRegistration, CreateOrder
from config import UserRole, EmployerStatus, ORDER_STATUS_NAMES

router = Router()
logger = logging.getLogger(__name__)


# ==== Регистрация работодателя ====

async def start_employer_registration(message: Message, state: FSMContext):
    """Начало регистрации работодателя"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if employer:
            if employer.status == EmployerStatus.APPROVED:
                await message.answer("✅ Вы уже зарегистрированы и прошли проверку!")
                return
            elif employer.status == EmployerStatus.PENDING:
                await message.answer(
                    "⏳ Ваша анкета на проверке у администратора.\n"
                    "Ожидайте уведомления."
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
    company_name = message.text.strip()
    
    if len(company_name) < 2:
        await message.answer("❌ Пожалуйста, введите корректное название компании:")
        return
    
    await state.update_data(company_name=company_name)
    await message.answer(
        f"✅ Компания: <b>{company_name}</b>\n\n"
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
        f"✅ Описание: {description or 'Не указано'}\n\n"
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
        f"✅ ИНН: {inn or 'Не указан'}\n\n"
        "👤 Введите <b>ФИО контактного лица</b>:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_person)


@router.message(EmployerRegistration.contact_person)
async def process_contact_person(message: Message, state: FSMContext):
    """Обработка контактного лица"""
    contact_person = message.text.strip()
    
    if len(contact_person) < 2:
        await message.answer("❌ Пожалуйста, введите корректное ФИО:")
        return
    
    await state.update_data(contact_person=contact_person)
    await message.answer(
        f"✅ Контактное лицо: <b>{contact_person}</b>\n\n"
        "📱 Введите <b>номер телефона</b> в формате:\n"
        "+7 (XXX) XXX-XX-XX или 8XXXXXXXXXX",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_phone)


@router.message(EmployerRegistration.contact_phone)
async def process_contact_phone(message: Message, state: FSMContext):
    """Обработка телефона"""
    import re
    phone = message.text.strip()
    
    logger.info(f"Получен телефон: '{phone}'")
    
    phone_digits = re.sub(r'\D', '', phone)
    
    logger.info(f"Только цифры: '{phone_digits}', длина: {len(phone_digits)}")
    
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
    logger.info(f"Форматированный телефон: {formatted_phone}")
    
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
        except:
            pass
    
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


# ==== Мои заявки ====

@router.message(F.text == "📋 Мои заявки")
async def show_my_orders(message: Message):
    """Показать заявки работодателя"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if not employer:
            await message.answer("❌ Сначала необходимо пройти регистрацию.")
            return
        
        orders = await OrderService.get_employer_orders(session, employer.id)
        
        if not orders:
            await message.answer(
                "У вас пока нет заявок.\n\n"
                "Создайте первую заявку, нажав «➕ Создать заявку»."
            )
            return
        
        await message.answer(f"📋 Ваши заявки ({len(orders)}):")
        
        for order in orders[:10]:
            status_name = ORDER_STATUS_NAMES.get(order.status, order.status)
            text = (
                f"📌 Заявка #{order.id}\n"
                f"📍 {order.city}, {order.address}\n"
                f"📅 {order.shift_date.strftime('%d.%m.%Y')}\n"
                f"👥 Требуется: {order.workers_needed} чел.\n"
                f"💼 {order.category}\n"
                f"💰 {order.payment_display}\n"
                f"📊 Статус: {status_name}"
            )
            await message.answer(text, reply_markup=inline.get_order_actions_keyboard(order.id))


# ==== Создание заявки ====

@router.message(F.text == "➕ Создать заявку")
async def start_create_order(message: Message, state: FSMContext):
    """Начало создания заявки"""
    logger.info(f"Получен запрос на создание заявки от пользователя {message.from_user.id}")
    
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        logger.info(f"Работодатель найден: {employer is not None}")
        
        if not employer:
            await message.answer("❌ Сначала необходимо пройти регистрацию.")
            return
        
        logger.info(f"Статус работодателя: {employer.status}")
        
        if employer.status != EmployerStatus.APPROVED:
            await message.answer(
                "⏳ Ваша анкета еще не прошла проверку администратора.\n"
                "Дождитесь одобрения."
            )
            return
    
    logger.info("Отправка клавиатуры с категориями...")
    await message.answer(
        "📝 <b>Создание заявки на подбор работников</b>\n\n"
        "Выберите категорию работы:",
        reply_markup=inline.get_job_categories_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.category)
    logger.info("Состояние установлено: CreateOrder.category")


@router.callback_query(CreateOrder.category, F.data.startswith("job_cat_"))
async def process_order_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, callback.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await callback.message.edit_text("❌ Эта функция доступна только работодателям.")
            return
    
    category = callback.data.replace("job_cat_", "")
    await state.update_data(category=category)
    
    await callback.message.edit_text(
        f"✅ Категория: <b>{category}</b>\n\n"
        "📍 Выберите город:",
        reply_markup=inline.get_cities_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.city)


@router.callback_query(CreateOrder.city, F.data.startswith("city_"))
async def process_order_city(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора города"""
    city = callback.data.replace("city_", "")
    await state.update_data(city=city)
    
    await callback.message.edit_text(
        f"✅ Город: <b>{city}</b>\n\n"
        "📍 Введите адрес проведения работ:",
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.address)


@router.message(CreateOrder.address)
async def process_order_address(message: Message, state: FSMContext):
    """Обработка адреса"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await message.answer("❌ Эта функция доступна только работодателям.")
            return
    
    address = message.text.strip()
    
    if len(address) < 5:
        await message.answer("❌ Пожалуйста, введите корректный адрес (минимум 5 символов):")
        return
    
    await state.update_data(address=address)
    await message.answer(
        f"✅ Адрес: <b>{address}</b>\n\n"
        "📅 Выберите дату смены:",
        reply_markup=inline.get_date_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.shift_date)


@router.callback_query(CreateOrder.shift_date, F.data.startswith("date_"))
async def process_order_date(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора даты"""
    date_str = callback.data.replace("date_", "")
    
    # Парсим дату в формате DD-MM-YYYY
    from datetime import datetime
    try:
        shift_date = datetime.strptime(date_str, "%d-%m-%Y")
        await state.update_data(shift_date=shift_date)
        
        await callback.message.edit_text(
            f"✅ Дата: <b>{shift_date.strftime('%d.%m.%Y')}</b>\n\n"
            "⏰ Выберите продолжительность смены (в часах):",
            reply_markup=inline.get_duration_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(CreateOrder.shift_duration)
    except ValueError:
        await callback.answer("❌ Ошибка при обработке даты", show_alert=True)


@router.callback_query(CreateOrder.shift_duration, F.data.startswith("duration_"))
async def process_order_duration(callback: CallbackQuery, state: FSMContext):
    """Обработка продолжительности смены"""
    duration = int(callback.data.replace("duration_", ""))
    await state.update_data(shift_duration=duration)
    
    await callback.message.edit_text(
        f"✅ Продолжительность: <b>{duration} ч.</b>\n\n"
        "👥 Введите количество требуемых работников:",
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.workers_needed)


@router.message(CreateOrder.workers_needed)
async def process_workers_needed(message: Message, state: FSMContext):
    """Обработка количества работников"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await message.answer("❌ Эта функция доступна только работодателям.")
            return
    
    try:
        workers = int(message.text.strip())
        if workers < 1 or workers > 100:
            await message.answer("❌ Укажите количество от 1 до 100:")
            return
        
        await state.update_data(workers_needed=workers)
        await message.answer(
            f"✅ Количество работников: <b>{workers} чел.</b>\n\n"
            "💰 Выберите тип оплаты:",
            reply_markup=inline.get_payment_type_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(CreateOrder.payment_type)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число:")


@router.callback_query(CreateOrder.payment_type, F.data.startswith("payment_"))
async def process_payment_type(callback: CallbackQuery, state: FSMContext):
    """Обработка типа оплаты"""
    payment_type = callback.data.replace("payment_", "")
    await state.update_data(payment_type=payment_type)
    
    payment_name = "за смену" if payment_type == "per_shift" else "в час"
    
    await callback.message.edit_text(
        f"✅ Тип оплаты: <b>{payment_name}</b>\n\n"
        f"💵 Введите сумму оплаты {payment_name} (в рублях):",
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.payment_amount)


@router.message(CreateOrder.payment_amount)
async def process_payment_amount(message: Message, state: FSMContext):
    """Обработка суммы оплаты"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await message.answer("❌ Эта функция доступна только работодателям.")
            return
    
    try:
        amount = float(message.text.strip())
        if amount < 100 or amount > 100000:
            await message.answer("❌ Укажите сумму от 100 до 100 000 рублей:")
            return
        
        await state.update_data(payment_amount=amount)
        
        # Рассчитываем комиссию
        from config import calculate_commission
        data = await state.get_data()
        
        # Определяем сумму за смену для расчета комиссии
        if data["payment_type"] == "per_shift":
            shift_amount = amount
        else:
            # Если оплата почасовая, умножаем на продолжительность
            shift_amount = amount * data["shift_duration"]
        
        commission = calculate_commission(shift_amount)
        total_per_worker = shift_amount + commission
        total_cost = total_per_worker * data["workers_needed"]
        
        await state.update_data(commission=commission)
        
        payment_display = f"{amount:.0f} ₽ {'за смену' if data['payment_type'] == 'per_shift' else 'в час'}"
        
        await message.answer(
            f"✅ Оплата: <b>{payment_display}</b>\n\n"
            f"💼 <b>Расчет стоимости:</b>\n"
            f"• Оплата за смену: {shift_amount:.0f} ₽\n"
            f"• Комиссия: {commission:.0f} ₽\n"
            f"• Итого за 1 работника: {total_per_worker:.0f} ₽\n"
            f"• Всего ({data['workers_needed']} чел.): <b>{total_cost:.0f} ₽</b>\n\n"
            "📝 Введите описание работы:",
            parse_mode="HTML"
        )
        await state.set_state(CreateOrder.description)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную сумму (например: 1500 или 1500.50):")


@router.message(CreateOrder.description)
async def process_order_description(message: Message, state: FSMContext):
    """Обработка описания работы"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await message.answer("❌ Эта функция доступна только работодателям.")
            return
    
    description = message.text.strip()
    
    if len(description) < 10:
        await message.answer("❌ Описание должно содержать минимум 10 символов:")
        return
    
    await state.update_data(description=description)
    await message.answer(
        "✅ Описание сохранено\n\n"
        "📋 Укажите требования к работникам или нажмите /skip:",
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.requirements)


@router.message(CreateOrder.requirements)
async def process_order_requirements(message: Message, state: FSMContext):
    """Обработка требований и подтверждение заявки"""
    # Проверка роли
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        if not user or user.role != UserRole.EMPLOYER:
            await state.clear()
            await message.answer("❌ Эта функция доступна только работодателям.")
            return
    
    if message.text and message.text.startswith("/skip"):
        requirements = None
    else:
        requirements = message.text.strip() if message.text else None
    
    await state.update_data(requirements=requirements)
    
    # Собираем данные для подтверждения
    data = await state.get_data()
    
    from datetime import datetime
    shift_date = data["shift_date"]
    
    # Определяем сумму за смену
    if data["payment_type"] == "per_shift":
        shift_amount = data["payment_amount"]
        payment_display = f"{data['payment_amount']:.0f} ₽ за смену"
    else:
        shift_amount = data["payment_amount"] * data["shift_duration"]
        payment_display = f"{data['payment_amount']:.0f} ₽ в час"
    
    total_per_worker = shift_amount + data["commission"]
    total_cost = total_per_worker * data["workers_needed"]
    
    confirmation_text = (
        "╔══════════════════════╗\n"
        "    <b>📋 ПОДТВЕРЖДЕНИЕ ЗАЯВКИ</b>\n"
        "╚══════════════════════╝\n\n"
        f"<b>💼 Категория:</b> {data['category']}\n"
        f"<b>📍 Город:</b> {data['city']}\n"
        f"<b>📍 Адрес:</b> {data['address']}\n"
        f"<b>📅 Дата:</b> {shift_date.strftime('%d.%m.%Y')}\n"
        f"<b>⏰ Продолжительность:</b> {data['shift_duration']} ч.\n"
        f"<b>👥 Работников:</b> {data['workers_needed']} чел.\n"
        f"<b>💰 Оплата:</b> {payment_display}\n\n"
        f"<b>📝 Описание:</b>\n{data['description']}\n\n"
    )
    
    if requirements:
        confirmation_text += f"<b>📋 Требования:</b>\n{requirements}\n\n"
    
    confirmation_text += (
        f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃  <b>💰 СТОИМОСТЬ</b>        ┃\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
        f"  • Оплата за смену: {shift_amount:.0f} ₽\n"
        f"  • Комиссия: {data['commission']:.0f} ₽\n"
        f"  • За 1 работника: <b>{total_per_worker:.0f} ₽</b>\n"
        f"  • Всего: <b>{total_cost:.0f} ₽</b>\n\n"
        "Всё верно? Создаём заявку?"
    )
    
    await message.answer(
        confirmation_text,
        reply_markup=inline.get_confirmation_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(CreateOrder.confirmation)


@router.callback_query(CreateOrder.confirmation, F.data == "confirm_yes")
async def confirm_create_order(callback: CallbackQuery, state: FSMContext):
    """Подтверждение создания заявки"""
    data = await state.get_data()
    
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, callback.from_user.id)
        
        if not employer:
            await callback.message.edit_text("❌ Ошибка: профиль работодателя не найден")
            await state.clear()
            return
        
        # Создаем заявку
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
            requirements=data.get("requirements"),
            payment_type=data["payment_type"],
            payment_amount=data["payment_amount"]
        )
        
        # Уведомляем администраторов о новой заявке
        try:
            from bot.utils.notifications import notify_admins_new_order
            await notify_admins_new_order(order.id)
        except:
            pass
    
    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Заявка #{order.id} создана!</b>\n\n"
        "Ваша заявка отправлена на модерацию администратору.\n"
        "После одобрения она будет опубликована для работников.\n\n"
        "Вы получите уведомление о результатах проверки.",
        parse_mode="HTML"
    )
    
    # Показываем главное меню
    await callback.message.answer(
        "👔 <b>Главное меню</b>",
        reply_markup=reply.get_employer_menu(),
        parse_mode="HTML"
    )


@router.callback_query(CreateOrder.confirmation, F.data == "confirm_no")
async def cancel_create_order(callback: CallbackQuery, state: FSMContext):
    """Отмена создания заявки"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Создание заявки отменено.\n\n"
        "Используйте кнопки меню для навигации."
    )
    await callback.message.answer(
        "👔 <b>Главное меню</b>",
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
            f"<b>🏢 Компания:</b> {employer.company_name}\n"
            f"<b>👤 Контактное лицо:</b> {employer.contact_person}\n"
            f"<b>📱 Телефон:</b> <code>{employer.contact_phone}</code>\n"
        )
        
        if employer.contact_email:
            text += f"<b>📧 Email:</b> {employer.contact_email}\n"
        
        if employer.inn:
            text += f"<b>🏢 ИНН:</b> {employer.inn}\n"
        
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
        
        if photo_path.exists():
            photo = FSInputFile(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML"
            )
        else:
            await message.answer(text, parse_mode="HTML")
