"""
FSM состояния для бота
"""
from aiogram.fsm.state import State, StatesGroup


class WorkerRegistration(StatesGroup):
    """Регистрация работника"""
    policy_agreement = State()
    channel_subscription = State()
    city = State()
    name = State()
    phone = State()
    categories = State()


class EmployerRegistration(StatesGroup):
    """Регистрация работодателя"""
    company_name = State()
    company_description = State()
    inn = State()
    contact_person = State()
    contact_phone = State()
    contact_email = State()
    city = State()
    confirmation = State()


class CreateOrder(StatesGroup):
    """Создание заявки"""
    category = State()
    city = State()
    address = State()
    shift_date = State()
    shift_time = State()
    shift_duration = State()
    workers_needed = State()
    payment_type = State()
    payment_amount = State()
    description = State()
    requirements = State()
    confirmation = State()


class RateWorker(StatesGroup):
    """Оценка работника работодателем"""
    rating = State()
    comment = State()


class CheckIn(StatesGroup):
    """Отметка «я на месте»: ждём геолокацию"""
    location = State()


class DocUpload(StatesGroup):
    """Загрузка документа для проверки"""
    file = State()
