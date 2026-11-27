"""
Обработчики команды /start и выбора роли
"""
import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from database import async_session
from services import UserService, WorkerService, EmployerService
from bot.keyboards import reply, inline
from bot.states import WorkerRegistration
from bot.utils import referrals
from config import UserRole, CHANNEL_ID, ADMIN_CONTACT, REFERRAL_BONUS

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start (в том числе по реферальной ссылке /start ref_<id>)"""
    await state.clear()

    referrer_id = referrals.parse_payload(message.text)
    if referrer_id:
        try:
            await referrals.register_invite(message.from_user.id, referrer_id)
        except Exception:
            logger.exception("Не удалось записать приглашение")

    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
        
        if user and user.is_blocked:
            await message.answer(
                "❌ Ваш аккаунт заблокирован.\n"
                "Для получения подробной информации обратитесь к администратору."
            )
            return
        
        if user and user.role == UserRole.WORKER:
            worker = await WorkerService.get_worker(session, user.id)
            if not worker:
                # Роль выбрана, но регистрация не была завершена
                await message.answer(
                    "👷 Давайте завершим регистрацию работника.\n\n"
                    "Выберите ваш город:",
                    reply_markup=inline.get_cities_keyboard()
                )
                await state.set_state(WorkerRegistration.city)
                return
        
        if user and user.role == UserRole.EMPLOYER:
            employer = await EmployerService.get_employer(session, user.id)
            if not employer:
                from bot.handlers.employer import start_employer_registration
                await start_employer_registration(message, state, user_id=user.id)
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
    # callback.message отправлено ботом, поэтому передаём id пользователя явно
    await start_employer_registration(callback.message, state, user_id=callback.from_user.id)


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


@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия (сброс FSM)"""
    current_state = await state.get_state()
    await state.clear()
    
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
    
    text = "❌ Действие отменено." if current_state else "Нечего отменять."
    
    if user and user.role:
        await message.answer(text)
        await send_main_menu(message, user.role)
    else:
        await message.answer(
            f"{text}\n\nНажмите /start, чтобы начать.",
            reply_markup=ReplyKeyboardRemove()
        )


@router.message(Command("support"))
async def cmd_support(message: Message):
    """Связь с поддержкой"""
    await message.answer(
        "💬 <b>Поддержка СМЕНА</b>\n\n"
        f"По любым вопросам пишите администратору: {ADMIN_CONTACT}",
        parse_mode="HTML"
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    """Профиль пользователя в зависимости от роли"""
    await state.clear()
    
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
    
    if not user or not user.role:
        await message.answer("Вы ещё не зарегистрированы. Нажмите /start, чтобы начать.")
        return
    
    if user.role == UserRole.WORKER:
        from bot.handlers.worker import show_worker_profile
        await show_worker_profile(message)
    elif user.role == UserRole.EMPLOYER:
        from bot.handlers.employer import show_employer_profile
        await show_employer_profile(message)
    else:
        await send_main_menu(message, user.role)


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    """Команда помощи"""
    
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
                "1. «➕ Создать заявку»: 2–3 минуты, в конце вы проверите заявку целиком\n"
                "2. Администратор проверяет заявку (обычно до часа)\n"
                "3. Вакансию получают подходящие работники, о каждом подтверждённом мы сообщим\n"
                "4. После набора — предоплата части комиссии (кнопка «✅ Я оплатил»)\n"
                "5. За сутки до смены пришлём напоминание и сводку набора\n"
                "6. После смены нажмите «🏁 Смена завершена» и оцените работников\n"
                "7. Администратор закрывает расчёт\n\n"
                "Все заявки и их статус — в «📋 Мои заявки». Там же можно отменить заявку "
                "или повторить прошлую в один клик (🔁).\n\n"
                "💰 <b>Комиссия:</b> 5% (смена до 2 500 ₽), 10%, 12,5% (свыше 4 500 ₽) с каждого работника\n\n"
                f"📞 <b>Вопросы:</b> {ADMIN_CONTACT}"
            )
        else:  # WORKER
            help_text = (
                "ℹ️ <b>Справка для работников</b>\n\n"
                "✅ <b>Как это работает:</b>\n"
                "1. Укажите город и категории работы\n"
                "2. Получайте уведомления о новых вакансиях\n"
                "3. Откликайтесь на подходящие предложения\n"
                "4. Когда вас подтвердят, придёт сообщение с адресом и временем\n"
                "5. За сутки и за 2 часа напомним о смене, нажмите «👍 Буду на смене»\n"
                "6. Не получается выйти? Откажитесь заранее в «📝 Мои отклики»\n"
                "7. После смены работодатель оценит вашу работу\n\n"
                "⭐️ Копите рейтинг для повышения доверия!\n\n"
                f"📞 <b>Вопросы:</b> {ADMIN_CONTACT}"
            )
        
        await message.answer(help_text, parse_mode="HTML")


@router.message(Command("invite"))
@router.message(F.text == "🎁 Пригласить друга")
async def invite_friend(message: Message):
    """Реферальная ссылка и статистика приглашений"""
    async with async_session() as session:
        user = await UserService.get_user(session, message.from_user.id)
    if not user or not user.role:
        await message.answer("Сначала зарегистрируйтесь: нажмите /start.")
        return
    link = await referrals.invite_link(message.from_user.id)
    st = await referrals.stats(message.from_user.id)
    await message.answer(
        "🎁 <b>Приглашайте друзей в СМЕНУ</b>\n\n"
        f"За каждого друга, который выполнит первую смену (или работодателя, у которого "
        f"завершится первый заказ), вы получите <b>{REFERRAL_BONUS:.0f} ₽</b>.\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👥 Пришло по ссылке: {st['invited']}\n"
        f"✅ Стали активными: {st['qualified']}\n"
        f"💰 Начислено: {st['earned']:.0f} ₽ · выплачено: {st['paid']:.0f} ₽",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
