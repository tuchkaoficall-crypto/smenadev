"""
Inline клавиатуры для бота
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_policy_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура согласия с политикой"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я ознакомлен и согласен", callback_data="policy_agree")
    builder.adjust(1)
    return builder.as_markup()


def get_channel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подписки на канал"""
    from config import CHANNEL_URL
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Подписаться на канал", url=CHANNEL_URL)
    builder.button(text="✅ Я подписался", callback_data="channel_subscribed")
    builder.adjust(1)
    return builder.as_markup()


def get_role_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора роли"""
    builder = InlineKeyboardBuilder()
    builder.button(text="👔 Я работодатель", callback_data="role_employer")
    builder.button(text="👷 Я ищу работу", callback_data="role_worker")
    builder.adjust(1)
    return builder.as_markup()


def get_cities_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора города"""
    from config import AVAILABLE_CITIES
    builder = InlineKeyboardBuilder()
    for city in AVAILABLE_CITIES:
        builder.button(text=city, callback_data=f"city_{city}")
    builder.adjust(2)
    return builder.as_markup()


def get_categories_keyboard(selected: list = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора категорий работы"""
    from config import JOB_CATEGORIES
    if selected is None:
        selected = []
    
    builder = InlineKeyboardBuilder()
    for category in JOB_CATEGORIES:
        mark = "✅ " if category in selected else ""
        builder.button(
            text=f"{mark}{category}",
            callback_data=f"cat_{category}"
        )
    builder.button(text="⏭ Пропустить", callback_data="cat_skip")
    builder.button(text="✅ Завершить выбор", callback_data="cat_done")
    builder.adjust(2)
    return builder.as_markup()


def get_order_actions_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура действий с заказом"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📊 Статус заказа",
        callback_data=f"order_status:{order_id}"
    )
    builder.button(
        text="👥 Отклики",
        callback_data=f"order_responses:{order_id}"
    )
    builder.button(
        text="🗑 Отменить",
        callback_data=f"order_cancel:{order_id}"
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def get_response_button(order_id: int) -> InlineKeyboardMarkup:
    """Кнопка для отклика на вакансию"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Откликнуться",
        callback_data=f"respond:{order_id}"
    )
    return builder.as_markup()


def get_worker_profile_keyboard(worker_id: int) -> InlineKeyboardMarkup:
    """Клавиатура профиля работника"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⭐️ Отзывы",
        callback_data=f"worker_reviews:{worker_id}"
    )
    builder.button(
        text="📝 История смен",
        callback_data=f"worker_history:{worker_id}"
    )
    builder.adjust(2)
    return builder.as_markup()


def get_rate_worker_keyboard(order_id: int, worker_id: int) -> InlineKeyboardMarkup:
    """Кнопка для оценки работника"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⭐️ Оценить работника",
        callback_data=f"rate_worker:{order_id}:{worker_id}"
    )
    return builder.as_markup()


def get_response_actions_keyboard(response_id: int) -> InlineKeyboardMarkup:
    """Действия с откликом (для админа)"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data=f"confirm_response:{response_id}"
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=f"reject_response:{response_id}"
    )
    builder.button(
        text="💬 Связаться",
        callback_data=f"contact_worker:{response_id}"
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def get_order_moderation_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура модерации заказа"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Одобрить",
        callback_data=f"approve_order:{order_id}"
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=f"reject_order:{order_id}"
    )
    builder.adjust(2)
    return builder.as_markup()


def get_employer_moderation_keyboard(employer_id: int) -> InlineKeyboardMarkup:
    """Клавиатура модерации работодателя"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Одобрить",
        callback_data=f"approve_employer:{employer_id}"
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=f"reject_employer:{employer_id}"
    )
    builder.adjust(2)
    return builder.as_markup()


def get_pagination_keyboard(
    page: int,
    total_pages: int,
    callback_prefix: str
) -> InlineKeyboardMarkup:
    """Клавиатура пагинации"""
    builder = InlineKeyboardBuilder()
    
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"{callback_prefix}:{page-1}"
        ))
    
    buttons.append(InlineKeyboardButton(
        text=f"{page}/{total_pages}",
        callback_data="page_info"
    ))
    
    if page < total_pages:
        buttons.append(InlineKeyboardButton(
            text="Вперёд ▶️",
            callback_data=f"{callback_prefix}:{page+1}"
        ))
    
    builder.row(*buttons)
    return builder.as_markup()


def get_back_button(callback_data: str = "back") -> InlineKeyboardMarkup:
    """Кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback_data)
    return builder.as_markup()


def get_job_categories_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора категории работы для заявки"""
    from config import JOB_CATEGORIES
    builder = InlineKeyboardBuilder()
    for category in JOB_CATEGORIES:
        builder.button(text=category, callback_data=f"job_cat_{category}")
    builder.adjust(2)
    return builder.as_markup()


def get_date_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора даты (ближайшие 14 дней)"""
    from datetime import datetime, timedelta
    builder = InlineKeyboardBuilder()
    
    today = datetime.now()
    for i in range(14):
        date = today + timedelta(days=i)
        if i == 0:
            text = f"Сегодня ({date.strftime('%d.%m')})"
        elif i == 1:
            text = f"Завтра ({date.strftime('%d.%m')})"
        else:
            text = date.strftime('%d.%m (%a)')
        
        builder.button(
            text=text,
            callback_data=f"date_{date.strftime('%d-%m-%Y')}"
        )
    
    builder.adjust(2)
    return builder.as_markup()


def get_duration_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора продолжительности смены"""
    builder = InlineKeyboardBuilder()
    durations = [2, 4, 6, 8, 10, 12]
    
    for duration in durations:
        builder.button(
            text=f"{duration} часов",
            callback_data=f"duration_{duration}"
        )
    
    builder.adjust(3)
    return builder.as_markup()


def get_payment_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа оплаты"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 За смену", callback_data="payment_per_shift")
    builder.button(text="⏰ Почасовая", callback_data="payment_per_hour")
    builder.adjust(2)
    return builder.as_markup()


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения действия"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, всё верно", callback_data="confirm_yes")
    builder.button(text="❌ Нет, отменить", callback_data="confirm_no")
    builder.adjust(2)
    return builder.as_markup()
