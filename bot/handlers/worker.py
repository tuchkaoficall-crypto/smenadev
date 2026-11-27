"""
Обработчики для работников
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import json
import logging
from html import escape
from datetime import datetime

from database import async_session
from services import UserService, WorkerService, OrderService, ResponseService, ReviewService
from bot.keyboards import reply, inline
from bot.states import WorkerRegistration
from bot.handlers.worker_tools import profile_markup as _profile_markup
from services import order_texts as T
from services import reliability as R
from services.cities import is_active as is_active_city
from config import UserRole, ResponseStatus, OrderStatus, PENALTY_WINDOW_DAYS, ADMIN_CONTACT

router = Router()
logger = logging.getLogger(__name__)


# ==== Регистрация работника ====

@router.callback_query(WorkerRegistration.city, F.data.startswith("city_"))
async def process_worker_city(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора города при регистрации работника"""
    city = callback.data.split("_", 1)[1]
    if not is_active_city(city):
        await callback.answer("Этот город сейчас недоступен, выберите другой", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=inline.get_cities_keyboard())
        return
    await state.update_data(city=city)
    
    await callback.message.edit_text(
        f"✅ Город: <b>{escape(city)}</b>\n\n"
        "📝 Теперь введите ваше <b>имя и фамилию</b>:",
        parse_mode="HTML"
    )
    await state.set_state(WorkerRegistration.name)
    await callback.answer()


@router.message(WorkerRegistration.name)
async def process_worker_name(message: Message, state: FSMContext):
    """Обработка имени работника"""
    name = (message.text or "").strip()
    
    if len(name) < 2 or len(name) > 100:
        await message.answer("❌ Пожалуйста, введите корректное имя (от 2 до 100 символов):")
        return
    
    await state.update_data(name=name)
    
    # Обновляем имя пользователя
    async with async_session() as session:
        await UserService.update_user(
            session,
            user_id=message.from_user.id,
            first_name=name.split()[0] if name.split() else name,
            last_name=" ".join(name.split()[1:]) if len(name.split()) > 1 else None
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
    # Телефон можно ввести текстом или отправить контактом
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = (message.text or "").strip()
    
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
            f"👤 Имя: {escape(data['name'])}\n"
            f"📱 Телефон: {data['phone']}\n"
            f"📍 Город: {escape(data['city'])}\n"
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
            f"👤 Имя: {escape(data['name'])}\n"
            f"📱 Телефон: {data['phone']}\n"
            f"📍 Город: {escape(data['city'])}\n"
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
        else:
            await callback.answer()


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
        try:
            categories = json.loads(worker.categories) if worker.categories else []
        except (ValueError, TypeError):
            categories = []
        
        # Поиск вакансий
        all_orders = []
        if not categories:
            # «Любая работа» — показываем все активные вакансии города
            all_orders = await OrderService.get_active_orders_by_city(session, worker.city)
        else:
            for category in categories:
                orders = await OrderService.get_orders_by_city_and_category(
                    session,
                    worker.city,
                    category
                )
                all_orders.extend(orders)
        
        # Убираем дубликаты и смены, которые уже начались
        now = datetime.now()
        unique_orders = sorted(
            {o.id: o for o in all_orders if o.shift_date and o.shift_date > now}.values(),
            key=lambda o: o.shift_date,
        )
        
        if not unique_orders:
            await message.answer(
                "😔 К сожалению, сейчас нет доступных вакансий в вашем городе.\n\n"
                "Вы получите уведомление, когда появится подходящая работа.",
                reply_markup=reply.get_worker_menu()
            )
            return
        
        await message.answer(
            f"🔍 Найдено вакансий: {len(unique_orders)}\n\n"
            "Просмотрите доступные предложения:",
            reply_markup=reply.get_worker_menu()
        )
        
        for order in unique_orders[:20]:
            # Проверяем, откликнулся ли уже работник
            has_responded = await ResponseService.has_responded(
                session,
                worker.id,
                order.id
            )
            
            text = f"📌 <b>Вакансия #{order.id}</b>\n\n{T.order_details(order)}"

            if has_responded:
                text += "\n\n✅ Вы уже откликнулись на эту вакансию"
                await message.answer(text, parse_mode="HTML")
            else:
                await message.answer(
                    text,
                    parse_mode="HTML",
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
        
        if order.status != OrderStatus.SEARCH_WORKERS:
            await callback.answer("😔 Набор на эту вакансию уже закрыт.", show_alert=True)
            return
        
        if order.shift_date <= datetime.now():
            await callback.answer("😔 Эта смена уже началась.", show_alert=True)
            return
        
        # Повторное нажатие не должно создавать дубль и повторно дёргать админов
        if await ResponseService.has_responded(session, worker.id, order_id):
            await callback.answer("Вы уже откликнулись на эту вакансию", show_alert=True)
            return

        points = await R.worker_points_async(session, worker.id)
        if R.is_restricted(points):
            await callback.answer(
                f"⛔️ У вас {points} штрафных баллов (неявки или поздние отказы), отклики временно "
                f"недоступны. Баллы сгорают через {PENALTY_WINDOW_DAYS} дней. Вопросы: {ADMIN_CONTACT}",
                show_alert=True)
            return
        
        # Создаем отклик
        response = await ResponseService.create_response(
            session,
            order_id=order_id,
            worker_id=worker.id
        )
        
        # Уведомляем администраторов
        try:
            from bot.utils.notifications import notify_admins_new_response
            await notify_admins_new_response(response.id)
        except Exception as e:
            logger.exception("Ошибка уведомления админов об отклике: %s", e)
        
        try:
            await callback.message.edit_text(
                (callback.message.html_text or "") + "\n\n✅ Вы откликнулись на эту вакансию",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("Не удалось обновить сообщение вакансии: %s", e)
        
        await callback.answer(
            "✅ Отклик отправлен!\n"
            "Мы сообщим, когда вас подтвердят. Статус виден в «📝 Мои отклики».",
            show_alert=True
        )


# ==== Мои отклики ====

@router.message(F.text == "📝 Мои отклики")
async def show_my_responses(message: Message):
    """Отклики работника: сначала актуальные смены, с кнопками отказа"""
    from bot.utils import lifecycle as L
    from bot.keyboards.lifecycle import to_markup
    from services import order_keyboards as K

    async with async_session() as session:
        worker = await WorkerService.get_worker(session, message.from_user.id)
        if not worker:
            await message.answer("❌ Сначала необходимо пройти регистрацию.", reply_markup=reply.get_worker_menu())
            return
        responses = await ResponseService.get_worker_responses(session, worker.id)
        from bot.utils import checkin as C
        from database.models import ShiftCheckin
        from sqlalchemy import select
        checked = set((await session.execute(select(ShiftCheckin.response_id).where(
            ShiftCheckin.worker_id == worker.id))).scalars().all())

    def can_checkin(r):
        if r.id in checked:
            return False
        try:
            C.check_allowed(r, datetime.now())
            return True
        except C.CheckinError:
            return False

    if not responses:
        await message.answer(
            "У вас пока нет откликов.\n\nНайдите подходящую работу, нажав «🔍 Найти работу».",
            reply_markup=reply.get_worker_menu(),
        )
        return

    def is_actual(r):
        return r.order.status not in K.FINAL + K.DONE and r.status not in (
            ResponseStatus.REJECTED, ResponseStatus.WITHDRAWN)

    actual = sorted([r for r in responses if is_actual(r)], key=lambda r: r.order.shift_date)
    history = [r for r in responses if not is_actual(r)]

    await message.answer(
        f"📝 <b>Ваши отклики</b>\nАктуальных: {len(actual)} · в истории: {len(history)}",
        parse_mode="HTML", reply_markup=reply.get_worker_menu(),
    )
    for r in actual[:10]:
        text, rows = L.worker_response_card(r, r.order, can_checkin(r))
        if r.id in checked:
            text += "\n📍 Вы отметились на месте"
        await message.answer(text, parse_mode="HTML", reply_markup=to_markup(rows))

    if history:
        from config import RESPONSE_STATUS_NAMES
        lines = ["🗂 <b>История</b>"]
        for r in history[:10]:
            o = r.order
            lines.append(f"• #{o.id} {escape(o.category)}, {o.shift_date.strftime('%d.%m')} · "
                         f"{RESPONSE_STATUS_NAMES.get(r.status, r.status)}")
        await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.regexp(r"^wr:withdraw:\d+$"))
async def withdraw_ask(callback: CallbackQuery):
    """Отказ от отклика или смены: сначала подтверждение"""
    from bot.keyboards.lifecycle import yes_no
    response_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        if not response or response.worker.user_id != callback.from_user.id:
            await callback.answer("❌ Отклик не найден", show_alert=True)
            return
        confirmed = response.status == ResponseStatus.CONFIRMED
        order = response.order
    if confirmed:
        text = (f"⚠️ Отказаться от смены #{order.id} ({order.shift_date.strftime('%d.%m %H:%M')})?\n\n"
                "Работодатель и администратор получат уведомление и будут искать замену. "
                "Пожалуйста, отказывайтесь как можно раньше.")
        yes = "❌ Да, не смогу выйти"
    else:
        text = f"Отозвать отклик на вакансию #{order.id}?"
        yes = "↩️ Да, отозвать"
    await callback.message.answer(text, reply_markup=yes_no(yes, f"wr:withdrawyes:{response_id}"))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^wr:withdrawyes:\d+$"))
async def withdraw_yes(callback: CallbackQuery):
    from bot.utils import lifecycle as L
    response_id = int(callback.data.split(":")[2])
    try:
        was_confirmed = await L.withdraw_response(response_id, callback.from_user.id)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(
        "Вы отказались от смены. Спасибо, что предупредили заранее!" if was_confirmed
        else "Отклик отозван.")
    await callback.answer()


@router.callback_query(F.data.regexp(r"^wr:attend:\d+$"))
async def attend_ok(callback: CallbackQuery):
    """Работник подтвердил, что выйдет на смену (после напоминания)"""
    from bot.utils import lifecycle as L
    response_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        if not response or response.worker.user_id != callback.from_user.id:
            await callback.answer("❌ Отклик не найден", show_alert=True)
            return
        if response.status != ResponseStatus.CONFIRMED:
            await callback.answer("Эта смена уже неактуальна", show_alert=True)
            return
        await L.add_event(session, response.order_id, "attend_ok", callback.from_user.id)
        address = response.order.address
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(f"👍 Отлично, ждём вас! Адрес: {escape(address)}")
    await callback.answer()


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
        except (ValueError, TypeError):
            categories = []
        
        # Безопасное получение данных
        full_name = escape(user.full_name) if user else "Пользователь"
        phone = user.phone if user and user.phone else "Не указан"
        cats_text = ", ".join(categories) if categories else "Любая работа"
        
        # Формируем красивый текст профиля
        stars_count = int(round(worker.rating or 0))
        rating_stars = "⭐️" * stars_count + "☆" * (5 - stars_count)
        
        text = (
            f"╔══════════════════════╗\n"
            f"    <b>👤 ПРОФИЛЬ РАБОТНИКА</b>\n"
            f"╚══════════════════════╝\n\n"
            f"<b>👨‍💼 Имя:</b> {full_name}\n"
            f"<b>📱 Телефон:</b> <code>{phone}</code>\n"
            f"<b>📍 Город:</b> {escape(worker.city)}\n"
            f"<b>💼 Специализация:</b> {cats_text}\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃  <b>📊 СТАТИСТИКА</b>       ┃\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
            f"  {rating_stars} <b>{worker.rating:.1f}/5.0</b>\n"
            f"  ✅ Смен выполнено: <b>{worker.completed_shifts}</b>\n"
            f"  📅 На платформе с: <b>{worker.created_at.strftime('%d.%m.%Y')}</b>\n"
        )
        points = await R.worker_points_async(session, worker.id)
        lvl = R.level(points)
        text += f"  {lvl['emoji']} Надёжность: <b>{lvl['label']}</b>"
        text += f" ({points} б.)\n" if points else "\n"
        if worker.verified_at:
            text += "  🪪 Документы проверены\n"
        elif R.is_priority(worker, points):
            text += "  ⚡️ Получаете вакансии первым\n"

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
                        text += f"\n   <i>\"{escape(review.comment)}\"</i>"
                    text += f"\n   📅 {review.created_at.strftime('%d.%m.%Y')}\n"
            else:
                text += (
                    f"\n┏━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃  <b>💬 ОТЗЫВЫ</b>            ┃\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
                    f"  Пока нет отзывов\n"
                    f"  Выполните первую смену! 💪\n"
                )
        except Exception as e:
            logger.warning("Не удалось загрузить отзывы: %s", e)
        
        # Отправляем с фото
        from pathlib import Path
        from aiogram.types import FSInputFile
        from config import ASSETS_DIR
        
        photo_path = Path(ASSETS_DIR) / "smena_profile_1280x720.png"
        
        # Подпись к фото ограничена 1024 символами — длинный профиль шлём текстом
        markup = _profile_markup(worker, points)
        if photo_path.exists() and len(text) <= 1024:
            photo = FSInputFile(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            # Если фото нет, отправляем просто текст
            await message.answer(text, parse_mode="HTML", reply_markup=markup)
