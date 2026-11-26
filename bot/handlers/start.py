"""
Обработчики команды /start и выбора роли
"""
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from database import async_session
from services import UserService
from bot.keyboards import reply, inline
from bot.states import WorkerRegistration
from config import UserRole, CHANNEL_ID

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    await state.clear()
    
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        if user and user.is_blocked:
            await message.answer(
                "❌ Ваш аккаунт заблокирован.\n"
                "Для получения подробной информации обратитесь к администратору."
            )
            return
        
        if user and user.role:
            await send_main_menu(message, user.role)
            return
    
    # Показываем политику конфиденциальности (убираем reply клавиатуру)
    policy_text = (
        "👋 Добро пожаловать в СМЕНА!\n\n"
        "🔐 <b>Политика конфиденциальности</b>\n\n"
        "Мы — сервис-посредник для поиска временной работы.\n\n"
        "📌 <b>Важная информация:</b>\n"
        "• Бот является посредником между работодателями и работниками\n"
        "• Мы не несём ответственности за действия третьих лиц\n"
        "• Все условия работы согласовываются напрямую\n"
        "• Мы берём комиссию за подбор персонала\n"
        "• Ваши данные используются только для работы сервиса\n\n"
        "Нажимая кнопку ниже, вы соглашаетесь с условиями использования сервиса."
    )
    
    await message.answer(
        policy_text,
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    
    # Отправляем inline кнопку отдельным сообщением
    await message.answer(
        "Пожалуйста, ознакомьтесь с политикой выше:",
        reply_markup=inline.get_policy_keyboard()
    )
    await state.set_state(WorkerRegistration.policy_agreement)


@router.callback_query(F.data == "policy_agree")
async def policy_agreed(callback: CallbackQuery, state: FSMContext):
    """Пользователь согласился с политикой"""
    await callback.message.edit_text(
        "✅ Вы согласились с условиями использования сервиса.\n\n"
        "📢 <b>Подпишитесь на наш канал</b>\n\n"
        "Там мы публикуем актуальные вакансии, новости и полезную информацию.\n\n"
        "После подписки нажмите кнопку ниже.",
        reply_markup=inline.get_channel_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(WorkerRegistration.channel_subscription)
    await callback.answer()


@router.callback_query(F.data == "channel_subscribed")
async def channel_check(callback: CallbackQuery, state: FSMContext):
    """Проверка подписки на канал"""
    from bot.bot_instance import bot
    
    try:
        # Пробуем получить информацию о пользователе в канале
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=callback.from_user.id)
        
        # Проверяем статус подписки
        if member.status in ["member", "administrator", "creator"]:
            await callback.message.edit_text(
                "✅ Отлично! Вы подписаны на канал.\n\n"
                "Теперь выберите вашу роль:",
                reply_markup=inline.get_role_keyboard()
            )
            await state.clear()
            await callback.answer("✅ Проверка пройдена!")
        else:
            await callback.answer(
                "❌ Вы ещё не подписались на канал.\nПожалуйста, подпишитесь и попробуйте снова.",
                show_alert=True
            )
    except Exception as e:
        # Если бот не может проверить (не админ канала), п��едупреждаем но пропускаем
        await callback.message.edit_text(
            "⚠️ Не удалось проверить подписку автоматически.\n\n"
            "Пожалуйста, убедитесь, что вы подписались на канал!\n\n"
            "Теперь выберите вашу роль:",
            reply_markup=inline.get_role_keyboard()
        )
        await state.clear()
        await callback.answer("Продолжаем регистрацию...")


@router.callback_query(F.data == "role_employer")
async def choose_employer_role(callback: CallbackQuery, state: FSMContext):
    """Выбор роли работодателя"""
    async with async_session() as session:
        user = await UserService.get_user(session, callback.from_user.id)
        
        if not user:
            await UserService.create_user(
                session,
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                role=UserRole.EMPLOYER
            )
        else:
            await UserService.update_user(
                session,
                user_id=callback.from_user.id,
                role=UserRole.EMPLOYER
            )
    
    await callback.message.edit_text(
        "👔 Отлично! Вы выбрали роль работодателя.\n\n"
        "Для публикации заявок необходимо пройти регистрацию и проверку."
    )
    await callback.answer()
    
    # Импортируем здесь, чтобы избежать циклических импортов
    from bot.handlers.employer import start_employer_registration
    await start_employer_registration(callback.message, state)


@router.callback_query(F.data == "role_worker")
async def choose_worker_role(callback: CallbackQuery, state: FSMContext):
    """Выбор роли работника"""
    async with async_session() as session:
        user = await UserService.get_user(session, callback.from_user.id)
        
        if not user:
            await UserService.create_user(
                session,
                user_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                role=UserRole.WORKER
            )
        else:
            await UserService.update_user(
                session,
                user_id=callback.from_user.id,
                role=UserRole.WORKER
            )
    
    await callback.message.edit_text(
        "👷 Отлично! Вы выбрали роль работника.\n\n"
        "📝 Быстрая регистрация займёт всего минуту.\n\n"
        "Выберите ваш город:",
        reply_markup=inline.get_cities_keyboard()
    )
    await state.set_state(WorkerRegistration.city)
    await callback.answer()


async def send_main_menu(message: Message, role: str):
    """Отправка главного меню в зависимости от роли"""
    if role == UserRole.EMPLOYER:
        await message.answer(
            "👔 Главное меню работодателя",
            reply_markup=reply.get_employer_menu()
        )
    elif role == UserRole.WORKER:
        await message.answer(
            "👷 Главное меню работника",
            reply_markup=reply.get_worker_menu()
        )
    elif role == UserRole.ADMIN:
        await message.answer(
            "👨‍💼 Главное меню администратора\n\n"
            "Используйте админ-панель для управления сервисом."
        )


@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    """Команда помощи"""
    from config import ADMIN_CONTACT
    
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        if not user or not user.role:
            help_text = (
                "ℹ️ <b>Справка по боту СМЕНА</b>\n\n"
                "СМЕНА — это сервис поиска временной работы.\n\n"
                "Для начала работы выберите вашу роль:\n"
                "• 👔 Работодатель — если вам нужны сотрудники\n"
                "• 👷 Работник — если вы ищете подработку\n\n"
                "После регистрации вам будут доступны все возможности сервиса.\n\n"
                f"📞 <b>Администратор:</b> {ADMIN_CONTACT}"
            )
        elif user.role == UserRole.EMPLOYER:
            help_text = (
                "ℹ️ <b>Справка для работодателей</b>\n\n"
                "✅ <b>Как это работает:</b>\n"
                "1. Создайте заявку на подбор работников\n"
                "2. Дождитесь модерации\n"
                "3. Мы найдем подходящих кандидатов\n"
                "4. Вы подтвердите выбранных исполнителей\n"
                "5. Внесете предоплату\n"
                "6. Работники выходят на смену\n"
                "7. Оплатите услугу после завершения\n\n"
                "💰 <b>Комиссия:</b> 5-12.5% в зависимости от суммы\n\n"
                f"📞 <b>Вопросы:</b> {ADMIN_CONTACT}"
            )
        else:  # WORKER
            help_text = (
                "ℹ️ <b>Справка для работников</b>\n\n"
                "✅ <b>Как это работает:</b>\n"
                "1. Укажите город и категории работы\n"
                "2. Получайте уведомления о новых вакансиях\n"
                "3. Откликайтесь на подходящие предложения\n"
                "4. Администратор свяжется с вами\n"
                "5. Выходите на смену\n"
                "6. Получайте оплату от работодателя\n"
                "7. Получите положительный отзыв\n\n"
                "⭐️ Копите рейтинг для повышения доверия!\n\n"
                f"📞 <b>Вопросы:</b> {ADMIN_CONTACT}"
            )
        
        await message.answer(help_text, parse_mode="HTML")
