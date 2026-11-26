"""
Обработчики для работников
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import json
import logging

from database import async_session
from services import UserService, WorkerService, OrderService, ResponseService, ReviewService
from bot.keyboards import reply, inline
from bot.states import WorkerRegistration
from config import UserRole, ResponseStatus, OrderStatus

router = Router()
logger = logging.getLogger(__name__)


# ==== Регистрация работника ====

@router.callback_query(WorkerRegistration.city, F.data.startswith("city_"))
async def process_worker_city(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора города при регистрации работника"""
    city = callback.data.split("_", 1)[1]
    await state.update_data(city=city)
    
    await callback.message.edit_text(
        f"✅ Город: <b>{city}</b>\n\n"
        "📝 Теперь введите ваше <b>имя и фамилию</b>:",
        parse_mode="HTML"
    )
    await state.set_state(WorkerRegistration.name)
    await callback.answer()


@router.message(WorkerRegistration.name)
async def process_worker_name(message: Message, state: FSMContext):
    """Обработка имени работника"""
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Пожалуйста, введите корректное имя (минимум 2 символа):")
        return
    
    await state.update_data(name=name)
    
    # Обновляем имя пользователя
    async with async_session() as session:
        await UserService.update_user(
            session,
            user_id=message.from_user.id,
            first_name=name.split()[0] if name.split() else name,
            last_name=name.split()[1] if len(name.split()) > 1 else None
        )
    
    await message.answer(
        f"✅ Имя: {name}\n\n"
        "📱 Теперь введите ваш номер телефона в формате:\n"
        "+7 (XXX) XXX-XX-XX или 8XXXXXXXXXX"
    )
    await state.set_state(WorkerRegistration.phone)


@router.message(WorkerRegistration.phone)
async def process_worker_phone(message: Message, state: FSMContext):
    """Обработка телефона работника"""
    import re
    phone = message.text.strip()
    
    # Убираем все кроме цифр
    phone_digits = re.sub(r'\D', '', phone)
    
    # Проверяем формат
    if len(phone_digits) < 10 or len(phone_digits) > 11:
        await message.answer(
            "❌ Неверный формат номера. Пожалуйста, введите номер телефона:\n"
            "Например: +7 (900) 123-45-67 или 89001234567"
        )
        return
    
    # Форматируем номер
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    elif not phone_digits.startswith('7'):
        phone_digits = '7' + phone_digits
    
    formatted_phone = f"+{phone_digits}"
    
    # Обновляем телефон пользователя
    async with async_session() as session:
        await UserService.update_user(
            session,
            user_id=message.from_user.id,
            phone=formatted_phone
        )
    
    await state.update_data(phone=formatted_phone)
    
    data = await state.get_data()
    
    await message.answer(
        f"✅ Телефон: {formatted_phone}\n\n"
        "💼 Выберите категории работы, которые вас интересуют.\n\n"
        "Вы можете выбрать несколько категорий или пропустить этот шаг.",
        reply_markup=inline.get_categories_keyboard()
    )
    await state.update_data(categories=[])
    await state.set_state(WorkerRegistration.categories)


@router.callback_query(F.data.startswith("cat_"), WorkerRegistration.categories)
async def process_worker_categories(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категорий"""
    action = callback.data.split("_", 1)[1]
    
    data = await state.get_data()
    categories = data.get("categories", [])
    
    if action == "done":
        # Завершаем регистрацию
        async with async_session() as session:
            await WorkerService.create_worker(
                session,
                user_id=callback.from_user.id,
                city=data["city"],
                categories=categories
            )
        
        await state.clear()
        
        cats_text = ", ".join(categories) if categories else "Любая работа"
        
        await callback.message.edit_text(
            f"✅ <b>Регистрация завершена!</b>\n\n"
            f"👤 Имя: {data['name']}\n"
            f"📱 Телефон: {data['phone']}\n"
            f"📍 Город: {data['city']}\n"
            f"💼 Категории: {cats_text}\n\n"
            f"Вы будете получать уведомления о новых вакансиях.",
            parse_mode="HTML"
        )
        
        # Отправляем главное меню
        await callback.message.answer(
            "👷 <b>Главное меню работника</b>\n\n"
            "Используйте кнопки ниже для навигации:",
            reply_markup=reply.get_worker_menu(),
            parse_mode="HTML"
        )
        await callback.answer("✅ Добро пожаловать!")
        
    elif action == "skip":
        # Пропускаем выбор категорий
        async with async_session() as session:
            await WorkerService.create_worker(
                session,
                user_id=callback.from_user.id,
                city=data["city"],
                categories=[]
            )
        
        await state.clear()
        
        await callback.message.edit_text(
            f"✅ <b>Регистрация завершена!</b>\n\n"
            f"👤 Имя: {data['name']}\n"
            f"📱 Телефон: {data['phone']}\n"
            f"📍 Город: {data['city']}\n"
            f"💼 Категории: Любая работа\n\n"
            f"Вы будете получать уведомления о всех вакансиях.",
            parse_mode="HTML"
        )
        
        # Отправляем главное меню
        await callback.message.answer(
            "👷 <b>Главное меню работника</b>\n\n"
            "Используйте кнопки ниже для навигации:",
            reply_markup=reply.get_worker_menu(),
            parse_mode="HTML"
        )
        await callback.answer("✅ Добро пожаловать!")
        
    else:
        # Переключаем категорию
        from config import JOB_CATEGORIES
        
        if action in JOB_CATEGORIES:
            if action in categories:
                categories.remove(action)
            else:
                categories.append(action)
            
            await state.update_data(categories=categories)
            
            # Обновляем клавиатуру
            await callback.message.edit_reply_markup(
                reply_markup=inline.get_categories_keyboard(categories)
            )
            
            count = len(categories)
            await callback.answer(f"Выбрано категорий: {count}")


async def start_worker_registration(message: Message, state: FSMContext):
    """Начало регистрации работника (не используется, регистрация через callback)"""
    pass


# ==== Поиск работы ====

@router.message(F.text == "🔍 Найти работу")
async def find_jobs(message: Message):
    """Поиск доступных вакансий"""
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, message.from_user.id)
        
        if not worker:
            await message.answer(
                "❌ Сначала необходимо пройти регистрацию.",
                reply_markup=reply.get_worker_menu()
            )
            return
        
        # Получаем категории работника
        categories = json.loads(worker.categories)
        
        # Поиск вакансий
        all_orders = []
        for category in categories:
            orders = await OrderService.get_orders_by_city_and_category(
                session,
                worker.city,
                category
            )
            all_orders.extend(orders)
        
        # Убираем дубликаты
        unique_orders = {order.id: order for order in all_orders}.values()
        
        if not unique_orders:
            await message.answer(
                "😔 К сожалению, сейчас нет доступных вакансий в вашем городе.\n\n"
                "Вы получите уведомление, когда появится подходящая работа.",
                reply_markup=reply.get_worker_menu()
            )
            return
        
        await message.answer(
            f"🔍 Найдено вакансий: {len(list(unique_orders))}\n\n"
            "Просмотрите доступные предложения:",
            reply_markup=reply.get_worker_menu()
        )
        
        for order in unique_orders:
            # Проверяем, откликнулся ли уже работник
            has_responded = await ResponseService.has_responded(
                session,
                worker.id,
                order.id
            )
            
            text = (
                f"📌 Вакансия #{order.id}\n\n"
                f"💼 {order.category}\n"
                f"📍 {order.city}, {order.address}\n"
                f"📅 {order.shift_date.strftime('%d.%m.%Y')} в {order.shift_date.strftime('%H:%M')}\n"
                f"⏱ Продолжительность: {order.shift_duration} ч.\n"
                f"👥 Требуется: {order.workers_needed} чел.\n"
                f"💰 {order.payment_display}\n\n"
                f"📝 Описание:\n{order.description}"
            )
            
            if order.requirements:
                text += f"\n\n✅ Требования:\n{order.requirements}"
            
            if has_responded:
                text += "\n\n✅ Вы уже откликнулись на эту вакансию"
                await message.answer(text)
            else:
                await message.answer(
                    text,
                    reply_markup=inline.get_response_button(order.id)
                )


@router.callback_query(F.data.startswith("respond:"))
async def process_response(callback: CallbackQuery):
    """Обработка отклика на вакансию"""
    order_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, callback.from_user.id)
        order = await OrderService.get_order(session, order_id)
        
        if not worker or not order:
            await callback.answer("❌ Ошибка. Попробуйте снова.", show_alert=True)
            return
        
        # Создаем отклик
        response = await ResponseService.create_response(
            session,
            order_id=order_id,
            worker_id=worker.id
        )
        
        # Уведомляем администраторов
        from bot.utils.notifications import notify_admins_new_response
        await notify_admins_new_response(response.id)
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ Вы откликнулись на эту вакансию"
        )
        
        await callback.answer(
            "✅ Ваш отклик отправлен!\n"
            "Администратор свяжется с вами для уточнения деталей.",
            show_alert=True
        )


# ==== Мои отклики ====

@router.message(F.text == "📝 Мои отклики")
async def show_my_responses(message: Message):
    """Показать отклики работника"""
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, message.from_user.id)
        
        if not worker:
            await message.answer(
                "❌ Сначала необходимо пройти регистрацию.",
                reply_markup=reply.get_worker_menu()
            )
            return
        
        responses = await ResponseService.get_worker_responses(session, worker.id)
        
        if not responses:
            await message.answer(
                "У вас пока нет откликов.\n\n"
                "Найдите подходящую работу, нажав «🔍 Найти работу».",
                reply_markup=reply.get_worker_menu()
            )
            return
        
        await message.answer(
            f"📝 Ваши отклики ({len(responses)}):",
            reply_markup=reply.get_worker_menu()
        )
        
        from config import RESPONSE_STATUS_NAMES
        
        for response in responses[:10]:  # Показываем последние 10
            order = response.order
            status_name = RESPONSE_STATUS_NAMES.get(response.status, response.status)
            
            text = (
                f"📌 Вакансия #{order.id}\n"
                f"💼 {order.category}\n"
                f"📍 {order.city}, {order.address}\n"
                f"📅 {order.shift_date.strftime('%d.%m.%Y')}\n"
                f"💰 {order.payment_display}\n"
                f"📊 Статус отклика: {status_name}\n"
                f"🕐 Дата отклика: {response.created_at.strftime('%d.%m.%Y %H:%M')}"
            )
            
            if response.admin_comment:
                text += f"\n\n💬 Комментарий: {response.admin_comment}"
            
            await message.answer(text)


# ==== Профиль работника ====

@router.message(F.text == "👤 Мой профиль")
async def show_worker_profile(message: Message):
    """Показать профиль работника"""
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        if not user:
            await message.answer("❌ Пользователь не найден.")
            return
        
        if user.role != UserRole.WORKER:
            return
        
        worker = await WorkerService.get_worker(session, message.from_user.id)
        
        if not worker:
            await message.answer("❌ Профиль работника не найден.")
            return
        
        # Парсим категории
        try:
            categories = json.loads(worker.categories) if worker.categories else []
        except:
            categories = []
        
        # Безопасное получение данных
        full_name = user.full_name if user else "Пользователь"
        phone = user.phone if user and user.phone else "Не указан"
        cats_text = ", ".join(categories) if categories else "Любая работа"
        
        # Формируем красивый текст профиля
        rating_stars = "⭐️" * int(worker.rating) + "☆" * (5 - int(worker.rating))
        
        text = (
            f"╔══════════════════════╗\n"
            f"    <b>👤 ПРОФИЛЬ РАБОТНИКА</b>\n"
            f"╚══════════════════════╝\n\n"
            f"<b>👨‍💼 Имя:</b> {full_name}\n"
            f"<b>📱 Телефон:</b> <code>{phone}</code>\n"
            f"<b>📍 Город:</b> {worker.city}\n"
            f"<b>💼 Специализация:</b> {cats_text}\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  <b>📊 СТАТИСТИКА</b>       ┃\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
            f"  {rating_stars} <b>{worker.rating:.1f}/5.0</b>\n"
            f"  ✅ Смен выполнено: <b>{worker.completed_shifts}</b>\n"
            f"  📅 На платформе с: <b>{worker.created_at.strftime('%d.%m.%Y')}</b>\n"
        )
        
        # Показываем последние отзывы
        try:
            reviews = await ReviewService.get_worker_reviews(session, worker.id, limit=3)
            
            if reviews:
                text += (
                    f"\n┏━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  <b>💬 ОТЗЫВЫ</b>            ┃\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
                )
                for i, review in enumerate(reviews, 1):
                    rev_stars = "⭐️" * review.rating + "☆" * (5 - review.rating)
                    text += f"\n<b>{i}.</b> {rev_stars}"
                    if review.comment:
                        text += f"\n   <i>\"{review.comment}\"</i>"
                    text += f"\n   📅 {review.created_at.strftime('%d.%m.%Y')}\n"
            else:
                text += (
                    f"\n┏━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  <b>💬 ОТЗЫВЫ</b>            ┃\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
                    f"  Пока нет отзывов\n"
                    f"  Выполните первую смену! 💪\n"
                )
        except:
            pass
        
        # Отправляем с фото
        from pathlib import Path
        from aiogram.types import FSInputFile
        from config import ASSETS_DIR
        
        photo_path = Path(ASSETS_DIR) / "smena_profile_1280x720.png"
        
        if photo_path.exists():
            photo = FSInputFile(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML"
            )
        else:
            # Если фото нет, отправляем просто текст
            await message.answer(text, parse_mode="HTML")
