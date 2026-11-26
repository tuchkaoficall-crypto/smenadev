"""
Утилиты для отправки уведомлений
"""
from database import async_session
from services import EmployerService, OrderService, ResponseService, WorkerService
from config import ADMIN_IDS
import json


async def notify_admins_new_employer(employer_id: int):
    """Уведомить администраторов о новом работодателе"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_employer_moderation_keyboard
    
    async with async_session() as session:
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        
        if not employer:
            return
        
        text = (
            f"🆕 Новый работодатель на проверке\n\n"
            f"🏢 Компания: {employer.company_name}\n"
            f"👔 Контактное лицо: {employer.contact_person}\n"
            f"📞 Телефон: {employer.contact_phone}\n"
        )
        
        if employer.company_description:
            text += f"📝 Описание: {employer.company_description}\n"
        
        if employer.inn:
            text += f"🏦 ИНН: {employer.inn}\n"
        
        if employer.contact_email:
            text += f"📧 Email: {employer.contact_email}\n"
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=get_employer_moderation_keyboard(employer_id)
                )
            except:
                pass


async def notify_admins_new_order(order_id: int):
    """Уведомить администраторов о новом заказе"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_order_moderation_keyboard
    
    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        
        if not order:
            return
        
        text = (
            f"🆕 Новая заявка на модерации\n\n"
            f"📌 Заявка #{order.id}\n"
            f"🏢 Компания: {order.employer.company_name}\n"
            f"📍 {order.city}, {order.address}\n"
            f"📅 {order.shift_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"⏱ Продолжительность: {order.shift_duration} ч.\n"
            f"👥 Требуется: {order.workers_needed} чел.\n"
            f"💼 {order.category}\n"
            f"💰 {order.payment_display}\n\n"
            f"📝 Описание:\n{order.description}"
        )
        
        if order.requirements:
            text += f"\n\n✅ Требования:\n{order.requirements}"
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=get_order_moderation_keyboard(order_id)
                )
            except:
                pass


async def notify_admins_new_response(response_id: int):
    """Уведомить администраторов о новом отклике"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_response_actions_keyboard
    
    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        
        if not response:
            return
        
        order = response.order
        worker = response.worker
        
        text = (
            f"🆕 Новый отклик\n\n"
            f"📌 Вакансия #{order.id}\n"
            f"💼 {order.category}\n"
            f"📍 {order.city}\n\n"
            f"👤 Работник: {worker.user.full_name}\n"
            f"📞 {worker.user.phone}\n"
            f"⭐️ {worker.rating_display}\n"
            f"✅ Завершено смен: {worker.completed_shifts}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=get_response_actions_keyboard(response_id)
                )
            except:
                pass


async def notify_workers_new_order(order_id: int):
    """Уведомить подходящих работников о новой вакансии"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_response_button
    
    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        
        if not order:
            return
        
        # Находим подходящих работников
        workers = await WorkerService.search_workers_by_city_and_category(
            session,
            order.city,
            order.category
        )
        
        text = (
            f"🆕 Новая вакансия!\n\n"
            f"💼 {order.category}\n"
            f"📍 {order.city}, {order.address}\n"
            f"📅 {order.shift_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"⏱ Продолжительность: {order.shift_duration} ч.\n"
            f"👥 Требуется: {order.workers_needed} чел.\n"
            f"💰 {order.payment_display}\n\n"
            f"📝 Описание:\n{order.description}"
        )
        
        if order.requirements:
            text += f"\n\n✅ Требования:\n{order.requirements}"
        
        for worker in workers:
            try:
                # Проверяем, не откликнулся ли уже
                has_responded = await ResponseService.has_responded(
                    session,
                    worker.id,
                    order_id
                )
                
                if not has_responded:
                    await bot.send_message(
                        worker.user_id,
                        text,
                        reply_markup=get_response_button(order_id)
                    )
            except:
                pass


async def notify_employer_shift_completed(order_id: int):
    """Уведомить работодателя о завершении смены с просьбой оценить работников"""
    from bot.bot_instance import bot
    from bot.keyboards.inline import get_rate_worker_keyboard
    
    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        
        if not order:
            return
        
        # Получаем подтвержденных работников
        responses = await ResponseService.get_order_responses(
            session,
            order_id,
            ResponseStatus.CONFIRMED
        )
        
        text = (
            f"✅ Смена #{order_id} завершена!\n\n"
            f"Пожалуйста, оцените работников, чтобы помочь другим работодателям "
            f"в выборе исполнителей."
        )
        
        try:
            await bot.send_message(order.employer.user_id, text)
            
            # Отправляем кнопку для оценки каждого работника
            for response in responses:
                worker = response.worker
                worker_text = (
                    f"👤 {worker.user.full_name}\n"
                    f"⭐️ {worker.rating_display}"
                )
                
                await bot.send_message(
                    order.employer.user_id,
                    worker_text,
                    reply_markup=get_rate_worker_keyboard(order_id, worker.id)
                )
        except:
            pass
