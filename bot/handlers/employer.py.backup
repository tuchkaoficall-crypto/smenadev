"""
Обработчики для работодателей
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta

from database import async_session
from services import UserService, EmployerService, OrderService, ResponseService
from bot.keyboards import reply, inline
from bot.states import EmployerRegistration, CreateOrder
from config import UserRole, EmployerStatus, ORDER_STATUS_NAMES

router = Router()


# ==== Регистрация работодателя ====

async def start_employer_registration(message: Message, state: FSMContext):
    """Начало регистрации работодателя"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if employer:
            if employer.status == EmployerStatus.APPROVED:
                await message.answer(
                    "✅ Вы уже зарегистрированы и прошли проверку!"
                )
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
        await message.answer(
            "❌ Пожалуйста, введите корректное название компании:"
        )
        return
    
    await state.update_data(company_name=company_name)
    await message.answer(
        f"✅ Компания: <b>{company_name}</b>\n\n"
        "📝 Опишите деятельность вашей компании или нажмите /skip чтобы пропустить:",
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
        "🏢 Введите <b>ИНН компании</b> или /skip чтобы пропустить:",
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
    
    # Убираем все кроме цифр
    phone_digits = re.sub(r'\D', '', phone)
    
    if len(phone_digits) < 10 or len(phone_digits) > 11:
        await message.answer(
            "❌ Неверный формат номера. Введите номер телефона:\n"
            "Например: +7 (900) 123-45-67"
        )
        return
    
    # Форматируем
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    elif not phone_digits.startswith('7'):
        phone_digits = '7' + phone_digits
    
    formatted_phone = f"+{phone_digits}"
    
    await state.update_data(contact_phone=formatted_phone)
    await message.answer(
        f"✅ Телефон: <code>{formatted_phone}</code>\n\n"
        "📧 Введите <b>email</b> или /skip чтобы пропустить:",
        parse_mode="HTML"
    )
    await state.set_state(EmployerRegistration.contact_email)
    """Обработка ИНН"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Регистрация отменена.",
            reply_markup=reply.get_employer_menu()
        )
        return
    
    inn = None if message.text == "⏭ Пропустить" else message.text
    await state.update_data(inn=inn)
    
    await message.answer(
        "Введите ФИО контактного лица:",
        reply_markup=reply.get_cancel_keyboard()
    )
    await state.set_state(EmployerRegistration.contact_person)


@router.message(EmployerRegistration.contact_person)
async def process_contact_person(message: Message, state: FSMContext):
    """Обработка контактного лица"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Регистрация отменена.",
            reply_markup=reply.get_employer_menu()
        )
        return
    
    await state.update_data(contact_person=message.text)
    await message.answer(
        "Введите контактный телефон:",
        reply_markup=reply.get_phone_keyboard()
    )
    await state.set_state(EmployerRegistration.contact_phone)


@router.message(EmployerRegistration.contact_phone)
async def process_contact_phone(message: Message, state: FSMContext):
    """Обработка контактного телефона"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Регистрация отменена.",
            reply_markup=reply.get_employer_menu()
        )
        return
    
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(contact_phone=phone)
    
    await message.answer(
        "Введите email для связи (необязательно):",
        reply_markup=reply.get_skip_keyboard()
    )
    await state.set_state(EmployerRegistration.contact_email)


@router.message(EmployerRegistration.contact_email)
async def process_contact_email(message: Message, state: FSMContext):
    """Обработка email и завершение регистрации"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Регистрация отменена.",
            reply_markup=reply.get_employer_menu()
        )
        return
    
    email = None if message.text == "⏭ Пропустить" else message.text
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
        from config import ADMIN_IDS
        from bot.utils.notifications import notify_admins_new_employer
        await notify_admins_new_employer(employer.id)
    
    await state.clear()
    await message.answer(
        "✅ Регистрация завершена!\n\n"
        "Ваша анкета отправлена на проверку администратору.\n"
        "Вы получите уведомление о результатах проверки.",
        reply_markup=reply.get_employer_menu()
    )


# ==== Создание заявки ====

@router.message(F.text == "➕ Создать заявку")
async def start_create_order(message: Message, state: FSMContext):
    """Начало создания заявки"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if not employer:
            await message.answer(
                "❌ Сначала необходимо пройти регистрацию.",
                reply_markup=reply.get_employer_menu()
            )
            return
        
        if employer.status != EmployerStatus.APPROVED:
            await message.answer(
                "❌ Ваша анкета ещё не прошла проверку.\n"
                "Дождитесь одобрения администратора.",
                reply_markup=reply.get_employer_menu()
            )
            return
    
    await message.answer(
        "📝 Создание новой заявки\n\n"
        "Выберите город:",
        reply_markup=reply.get_cities_keyboard()
    )
    await state.set_state(CreateOrder.city)


@router.message(CreateOrder.city)
async def process_order_city(message: Message, state: FSMContext):
    """Обработка города"""
    from config import AVAILABLE_CITIES
    
    if message.text not in AVAILABLE_CITIES:
        await message.answer(
            "❌ Пожалуйста, выберите город из списка:",
            reply_markup=reply.get_cities_keyboard()
        )
        return
    
    await state.update_data(city=message.text)
    await message.answer(
        "Введите адрес работы:",
        reply_markup=reply.get_cancel_keyboard()
    )
    await state.set_state(CreateOrder.address)


@router.message(CreateOrder.address)
async def process_order_address(message: Message, state: FSMContext):
    """Обработка адреса"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Создание заявки отменено.",
            reply_markup=reply.get_employer_menu()
        )
        return
    
    await state.update_data(address=message.text)
    await message.answer(
        "Введите дату смены (в формате ДД.ММ.ГГГГ, например 25.05.2024):",
        reply_markup=reply.get_cancel_keyboard()
    )
    await state.set_state(CreateOrder.shift_date)


# Продолжение обработчиков создания заказа будет в следующем файле
# из-за ограничения по размеру...

@router.message(F.text == "📋 Мои заявки")
async def show_my_orders(message: Message):
    """Показать заявки работодателя"""
    async with async_session() as session:
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if not employer:
            await message.answer(
                "❌ Сначала необходимо пройти регистрацию.",
                reply_markup=reply.get_employer_menu()
            )
            return
        
        orders = await OrderService.get_employer_orders(session, employer.id)
        
        if not orders:
            await message.answer(
                "У вас пока нет заявок.\n\n"
                "Создайте первую заявку, нажав «➕ Создать заявку».",
                reply_markup=reply.get_employer_menu()
            )
            return
        
        await message.answer(
            f"📋 Ваши заявки ({len(orders)}):\n\n"
            "Выберите заявку для просмотра:",
            reply_markup=reply.get_employer_menu()
        )
        
        for order in orders[:10]:  # Показываем последние 10
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
            
            await message.answer(
                text,
                reply_markup=inline.get_order_actions_keyboard(order.id)
            )


@router.message(F.text == "👤 Мой профиль")
async def show_employer_profile(message: Message):
    """Показать профиль работодателя"""
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        # Проверяем роль пользователя
        if user and user.role != UserRole.EMPLOYER:
            return  # Пропускаем, пусть обработает другой роутер
        
        employer = await EmployerService.get_employer(session, message.from_user.id)
        
        if not employer:
            await message.answer(
                "❌ Профиль не найден. Пройдите регистрацию.",
                reply_markup=reply.get_employer_menu()
            )
            return
        
        from config import EMPLOYER_STATUS_NAMES
        status_name = EMPLOYER_STATUS_NAMES.get(employer.status, employer.status)
        
        orders = await OrderService.get_employer_orders(session, employer.id)
        
        text = (
            f"👤 Профиль работодателя\n\n"
            f"🏢 Компания: {employer.company_name}\n"
            f"👔 Контактное лицо: {employer.contact_person}\n"
            f"📞 Телефон: {employer.contact_phone}\n"
        )
        
        if employer.contact_email:
            text += f"📧 Email: {employer.contact_email}\n"
        
        text += (
            f"\n📊 Статус: {status_name}\n"
            f"📋 Создано заявок: {len(orders)}\n"
            f"📅 Регистрация: {employer.created_at.strftime('%d.%m.%Y')}"
        )
        
        await message.answer(text, reply_markup=reply.get_employer_menu())
