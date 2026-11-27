"""
Reply клавиатуры для бота
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_role_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора роли"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="👔 Я работодатель")
    builder.button(text="👷 Я ищу работу")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)


def get_phone_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для запроса телефона"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Поделиться номером", request_contact=True)
    return builder.as_markup(resize_keyboard=True)


def get_cities_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора города"""
    from services.cities import active_cities

    builder = ReplyKeyboardBuilder()
    for city in active_cities():
        builder.button(text=city)
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_categories_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора категорий работы"""
    from config import JOB_CATEGORIES
    
    builder = ReplyKeyboardBuilder()
    for category in JOB_CATEGORIES:
        builder.button(text=category)
    builder.button(text="✅ Завершить выбор")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_employer_menu() -> ReplyKeyboardMarkup:
    """Главное меню работодателя"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Создать заявку")
    builder.button(text="📋 Мои заявки")
    builder.button(text="👔 Мой профиль")
    builder.button(text="🎁 Пригласить друга")
    builder.button(text="❓ Помощь")
    builder.adjust(1, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите действие в меню")


def get_worker_menu() -> ReplyKeyboardMarkup:
    """Главное меню работника"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔍 Найти работу")
    builder.button(text="📝 Мои отклики")
    builder.button(text="👤 Мой профиль")
    builder.button(text="🎁 Пригласить друга")
    builder.button(text="❓ Помощь")
    builder.adjust(1, 2, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите действие в меню")


def get_payment_type_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора типа оплаты"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="💰 За смену")
    builder.button(text="⏱ За час")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура подтверждения"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="✅ Да, всё верно")
    builder.button(text="❌ Отмена")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)


def get_skip_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой пропуска"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="⏭ Пропустить")
    builder.button(text="❌ Отмена")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_rating_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для выбора рейтинга"""
    builder = ReplyKeyboardBuilder()
    for i in range(1, 6):
        builder.button(text=f"{'★' * i}")
    builder.button(text="❌ Отмена")
    builder.adjust(5, 1)
    return builder.as_markup(resize_keyboard=True)
