"""
Обработчики для администратора
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database import async_session
from services import EmployerService, OrderService, ResponseService, UserService
from bot.keyboards import inline
from config import ADMIN_IDS, EmployerStatus, OrderStatus, ResponseStatus

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


# ==== Модерация работодателей ====

@router.callback_query(F.data.startswith("approve_employer:"))
async def approve_employer(callback: CallbackQuery):
    """Одобрить работодателя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    employer_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        
        if not employer:
            await callback.answer("❌ Работодатель не найден", show_alert=True)
            return
        
        await EmployerService.approve_employer(session, employer_id)
        
        # Уведомляем работодателя
        from bot.bot_instance import bot
        try:
            await bot.send_message(
                employer.user_id,
                "✅ Поздравляем! Ваша анкета одобрена.\n\n"
                "Теперь вы можете создавать заявки на подбор работников."
            )
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ ОДОБРЕН"
        )
        await callback.answer("✅ Работодатель одобрен")


@router.callback_query(F.data.startswith("reject_employer:"))
async def reject_employer(callback: CallbackQuery):
    """Отклонить работодателя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    employer_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        
        if not employer:
            await callback.answer("❌ Работодатель не найден", show_alert=True)
            return
        
        reason = "Не прошел проверку"  # TODO: Добавить форму для ввода причины
        await EmployerService.reject_employer(session, employer_id, reason)
        
        # Уведомляем работодателя
        from bot.bot_instance import bot
        try:
            await bot.send_message(
                employer.user_id,
                f"❌ К сожалению, ваша анкета отклонена.\n\n"
                f"Причина: {reason}"
            )
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ ОТКЛОНЁН"
        )
        await callback.answer("❌ Работодатель отклонён")


# ==== Модерация заказов ====

@router.callback_query(F.data.startswith("approve_order:"))
async def approve_order(callback: CallbackQuery):
    """Одобрить заказ и начать поиск работников"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    order_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        await OrderService.approve_order(session, order_id)
        
        # Уведомляем работодателя
        from bot.bot_instance import bot
        try:
            await bot.send_message(
                order.employer.user_id,
                f"✅ Ваша заявка #{order_id} одобрена!\n\n"
                f"Начинаем поиск работников."
            )
        except:
            pass
        
        # Уведомляем подходящих работников
        from bot.utils.notifications import notify_workers_new_order
        await notify_workers_new_order(order_id)
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ ОДОБРЕН"
        )
        await callback.answer("✅ Заказ одобрен, начат поиск работников")


@router.callback_query(F.data.startswith("reject_order:"))
async def reject_order(callback: CallbackQuery):
    """Отклонить заказ"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    order_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        order = await OrderService.get_order(session, order_id)
        
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return
        
        reason = "Не соответствует требованиям"  # TODO: Добавить форму для ввода причины
        await OrderService.reject_order(session, order_id, reason)
        
        # Уведомляем работодателя
        from bot.bot_instance import bot
        try:
            await bot.send_message(
                order.employer.user_id,
                f"❌ Ваша заявка #{order_id} отклонена.\n\n"
                f"Причина: {reason}"
            )
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ ОТКЛОНЁН"
        )
        await callback.answer("❌ Заказ отклонён")


# ==== Работа с откликами ====

@router.callback_query(F.data.startswith("confirm_response:"))
async def confirm_response(callback: CallbackQuery):
    """Подтвердить отклик работника"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    response_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        
        if not response:
            await callback.answer("❌ Отклик не найден", show_alert=True)
            return
        
        await ResponseService.confirm_response(session, response_id)
        
        # Уведомляем работника
        from bot.bot_instance import bot
        try:
            await bot.send_message(
                response.worker.user_id,
                f"✅ Вас подтвердили на вакансию #{response.order_id}!\n\n"
                f"Ожидайте дальнейших инструкций."
            )
        except:
            pass
        
        # Уведомляем работодателя
        try:
            await bot.send_message(
                response.order.employer.user_id,
                f"✅ Работник найден для заявки #{response.order_id}!\n\n"
                f"Мы свяжемся с вами для дальнейшего согласования."
            )
        except:
            pass
        
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ ПОДТВЕРЖДЁН"
        )
        await callback.answer("✅ Отклик подтверждён")


@router.callback_query(F.data.startswith("reject_response:"))
async def reject_response(callback: CallbackQuery):
    """Отклонить отклик работника"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    response_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        
        if not response:
            await callback.answer("❌ Отклик не найден", show_alert=True)
            return
        
        reason = "Не подходит по требованиям"  # TODO: Добавить форму
        await ResponseService.reject_response(session, response_id, reason)
        
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ ОТКЛОНЁН"
        )
        await callback.answer("❌ Отклик отклонён")


# ==== Команды администратора ====

@router.message(Command("admin"))
async def admin_panel(message: Message):
    """Админ-панель (базовая статистика)"""
    if not is_admin(message.from_user.id):
        return
    
    async with async_session() as session:
        # Получаем статистику
        pending_employers = await EmployerService.get_pending_employers(session)
        pending_orders = await OrderService.get_orders_by_status(session, OrderStatus.MODERATION)
        
        text = (
            "👨‍💼 Админ-панель СМЕНА\n\n"
            f"📊 Статистика:\n"
            f"• Работодателей на проверке: {len(pending_employers)}\n"
            f"• Заказов на модерации: {len(pending_orders)}\n\n"
            "Используйте веб-панель для полного управления сервисом."
        )
        
        await message.answer(text)
