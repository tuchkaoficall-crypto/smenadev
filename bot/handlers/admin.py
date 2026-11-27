"""
Обработчики для администратора.

Модерация, отклики и весь жизненный цикл заказа прямо в Telegram:
  /orders         — активные заказы с кнопками
  /order <номер>  — карточка заказа со «следующими шагами»
  /complete <номер> — быстро завершить смену
Шаги и проверки совпадают с веб-панелью (bot/utils/lifecycle.py).
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from database import async_session
from database.models import Order
from services import EmployerService, OrderService, ResponseService
from services import order_texts as T
from bot.keyboards import inline
from bot.keyboards.lifecycle import to_markup
from bot.utils import lifecycle as L
from config import ADMIN_IDS, EmployerStatus, OrderStatus, ResponseStatus, RESPONSE_STATUS_NAMES

router = Router()
logger = logging.getLogger(__name__)

MODERATION_STATUSES = (OrderStatus.CREATED, OrderStatus.MODERATION)
ACTIVE_STATUSES = (
    OrderStatus.CREATED, OrderStatus.MODERATION, OrderStatus.SEARCH_WORKERS,
    OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT, OrderStatus.SHIFT_STARTED,
    OrderStatus.SHIFT_COMPLETED,
)

# Готовые причины: kind -> список. «Своя причина» вводится текстом.
REASONS = {
    "ro": ("Отклонение заявки", [
        "Недостаточно информации о работе",
        "Вакансия не подходит под правила сервиса",
        "Оплата ниже рыночной",
        "Дублирует другую заявку",
    ]),
    "co": ("Отмена заказа", [
        "По просьбе работодателя",
        "Не удалось набрать работников",
        "Не внесена предоплата",
        "Смена перенесена",
    ]),
    "re": ("Отклонение работодателя", [
        "Не удалось проверить компанию",
        "Неверные контактные данные",
        "Деятельность не подходит сервису",
    ]),
    "rr": ("Отклонение отклика", [
        "Не подходит по требованиям",
        "Набор уже закрыт",
        "Не удалось связаться",
    ]),
}


class AdminReason(StatesGroup):
    text = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def actor_name(user) -> str:
    return f"@{user.username}" if user.username else str(user.id)


async def _deny(callback: CallbackQuery) -> bool:
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return True
    return False


async def _mark_message(callback: CallbackQuery, suffix: str):
    """Дописать отметку к сообщению и убрать кнопки"""
    try:
        if callback.message.text:
            await callback.message.edit_text(callback.message.html_text + suffix, parse_mode="HTML")
        else:
            await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning("Не удалось обновить сообщение: %s", e)


async def _show_card(target: Message, order_id: int, edit: bool = False, header: str = None):
    async with async_session() as session:
        order = await L.get_order(session, order_id)
        if not order:
            await target.answer(f"❌ Заказ #{order_id} не найден")
            return
        text, rows = await L.admin_card(session, order)
    if header:
        text = f"{header}\n\n{text}"
    if edit:
        try:
            await target.edit_text(text, parse_mode="HTML", reply_markup=to_markup(rows))
            return
        except Exception as e:
            if "not modified" in str(e):
                return
            logger.debug("Карточку не отредактировать, шлём новую: %s", e)
    await target.answer(text, parse_mode="HTML", reply_markup=to_markup(rows))


def _reason_keyboard(kind: str, entity_id: int):
    _, reasons = REASONS[kind]
    rows = [[(r, f"rsn:{kind}:{entity_id}:{i}")] for i, r in enumerate(reasons)]
    rows.append([("✍️ Своя причина", f"rsn:{kind}:{entity_id}:c"), ("↩️ Передумал", "rsn_back")])
    return to_markup(rows)


async def _ask_reason(callback: CallbackQuery, kind: str, entity_id: int):
    title, _ = REASONS[kind]
    await callback.message.answer(
        f"❓ <b>{title} #{entity_id}</b>\nВыберите причину, её увидит пользователь:",
        parse_mode="HTML", reply_markup=_reason_keyboard(kind, entity_id))
    await callback.answer()


async def _apply_reason(kind: str, entity_id: int, reason: str, user) -> str:
    """Выполнить действие с причиной. Возвращает текст результата"""
    actor = actor_name(user)
    if kind == "ro":
        await L.reject_order(entity_id, reason, actor)
        return f"❌ Заявка #{entity_id} отклонена: {reason}"
    if kind == "co":
        await L.cancel_order(entity_id, reason, actor)
        return f"🗑 Заказ #{entity_id} отменён: {reason}"
    if kind == "rr":
        await L.reject_response(entity_id, reason, actor)
        return f"❌ Отклик #{entity_id} отклонён: {reason}"
    if kind == "re":
        async with async_session() as session:
            employer = await EmployerService.get_employer_by_id(session, entity_id)
            if not employer:
                raise L.LifecycleError("Работодатель не найден")
            if employer.status == EmployerStatus.REJECTED:
                raise L.LifecycleError("Анкета уже отклонена")
            await EmployerService.reject_employer(session, entity_id, reason)
            chat = employer.user_id
        await L.send(chat, f"❌ К сожалению, ваша анкета отклонена.\n\nПричина: {T.escape(reason)}\n\n"
                           "Вы можете заполнить анкету заново: нажмите /start.")
        return f"❌ Работодатель #{entity_id} отклонён: {reason}"
    raise L.LifecycleError("Неизвестное действие")


@router.callback_query(F.data.startswith("rsn:"))
async def reason_chosen(callback: CallbackQuery, state: FSMContext):
    if await _deny(callback):
        return
    _, kind, entity_id, idx = callback.data.split(":")
    entity_id = int(entity_id)
    if idx == "c":
        await state.set_state(AdminReason.text)
        await state.update_data(reason_kind=kind, reason_id=entity_id)
        await callback.message.edit_text(
            f"✍️ Напишите причину одним сообщением ({REASONS[kind][0].lower()} #{entity_id}).\n"
            "/cancel — отменить.")
        await callback.answer()
        return
    reason = REASONS[kind][1][int(idx)]
    try:
        result = await _apply_reason(kind, entity_id, reason, callback.from_user)
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(result)
    await callback.answer("Готово")


@router.callback_query(F.data == "rsn_back")
async def reason_back(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Действие не выполнено")


@router.message(AdminReason.text)
async def reason_typed(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    reason = (message.text or "").strip()
    if len(reason) < 3:
        await message.answer("Причина слишком короткая, напишите подробнее:")
        return
    data = await state.get_data()
    await state.clear()
    try:
        result = await _apply_reason(data["reason_kind"], data["reason_id"], reason[:500], message.from_user)
    except L.LifecycleError as e:
        await message.answer(f"❌ {e}")
        return
    await message.answer(result)


# ==== Модерация работодателей ====

@router.callback_query(F.data.startswith("approve_employer:"))
async def approve_employer(callback: CallbackQuery):
    if await _deny(callback):
        return
    employer_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        if not employer:
            await callback.answer("❌ Работодатель не найден", show_alert=True)
            return
        if employer.status == EmployerStatus.APPROVED:
            await callback.answer("Работодатель уже одобрен", show_alert=True)
            await _mark_message(callback, "\n\n✅ ОДОБРЕН")
            return
        await EmployerService.approve_employer(session, employer_id)
        chat = employer.user_id

    await L.send(chat,
                 "✅ <b>Поздравляем! Ваша анкета одобрена.</b>\n\n"
                 "Теперь вы можете создавать заявки на подбор работников: "
                 "нажмите «➕ Создать заявку». Это займёт 2–3 минуты.")
    await _mark_message(callback, "\n\n✅ ОДОБРЕН")
    await callback.answer("✅ Работодатель одобрен")


@router.callback_query(F.data.startswith("reject_employer:"))
async def reject_employer(callback: CallbackQuery):
    if await _deny(callback):
        return
    await _ask_reason(callback, "re", int(callback.data.split(":")[1]))


# ==== Модерация заказов (кнопки из уведомлений и карточек) ====

async def _do_approve(callback: CallbackQuery, order_id: int):
    try:
        sent = await L.approve_order(order_id, actor_name(callback.from_user))
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await _show_card(callback.message, order_id, edit=True,
                     header=f"✅ Одобрено, вакансия разослана {sent} работникам")
    await callback.answer("✅ Заказ одобрен")


@router.callback_query(F.data.startswith("approve_order:"))
async def approve_order(callback: CallbackQuery):
    if await _deny(callback):
        return
    await _do_approve(callback, int(callback.data.split(":")[1]))


@router.callback_query(F.data.startswith("reject_order:"))
async def reject_order(callback: CallbackQuery):
    if await _deny(callback):
        return
    await _ask_reason(callback, "ro", int(callback.data.split(":")[1]))


# ==== Работа с откликами ====

@router.callback_query(F.data.startswith("confirm_response:"))
async def confirm_response(callback: CallbackQuery):
    if await _deny(callback):
        return
    response_id = int(callback.data.split(":")[1])
    try:
        confirmed, needed, filled = await L.confirm_response(response_id, actor_name(callback.from_user))
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    suffix = f"\n\n✅ ПОДТВЕРЖДЁН ({confirmed}/{needed})"
    if filled:
        suffix += "\n👥 Набор закрыт"
    await _mark_message(callback, suffix)
    await callback.answer("✅ Отклик подтверждён")
    if filled:
        async with async_session() as session:
            response = await ResponseService.get_response(session, response_id)
            order_id = response.order_id
        await _show_card(callback.message, order_id,
                         header="🎉 Набор закрыт. Следующий шаг: предоплата или начало смены")


@router.callback_query(F.data.startswith("reject_response:"))
async def reject_response(callback: CallbackQuery):
    if await _deny(callback):
        return
    await _ask_reason(callback, "rr", int(callback.data.split(":")[1]))


@router.callback_query(F.data.startswith("contact_worker:"))
async def contact_worker(callback: CallbackQuery):
    if await _deny(callback):
        return
    response_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        response = await ResponseService.get_response(session, response_id)
        if not response:
            await callback.answer("❌ Отклик не найден", show_alert=True)
            return
        user = response.worker.user
        if response.status == ResponseStatus.PENDING:
            await ResponseService.update_status(session, response_id, ResponseStatus.CONTACTED)

    text = f"👤 {T.escape(user.full_name)}\n📞 {user.phone or 'телефон не указан'}\n"
    if user.username:
        text += f"💬 @{user.username}\n"
    text += f'🆔 <a href="tg://user?id={user.id}">написать в Telegram</a>'
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ==== Карточка заказа: «следующие шаги» ====

@router.callback_query(F.data.startswith("ao:"))
async def admin_order_action(callback: CallbackQuery):
    if await _deny(callback):
        return
    _, action, order_id = callback.data.split(":")
    order_id = int(order_id)
    actor = actor_name(callback.from_user)

    if action == "card":
        await _show_card(callback.message, order_id, edit=True)
        await callback.answer()
        return
    if action == "resp":
        await _show_responses(callback, order_id)
        return
    if action == "approve":
        await _do_approve(callback, order_id)
        return
    if action == "reject":
        await _ask_reason(callback, "ro", order_id)
        return
    if action == "cancel":
        await _ask_reason(callback, "co", order_id)
        return

    try:
        if action == "prep":
            amount = await L.request_prepayment(order_id, actor)
            note = f"💳 Запрошена предоплата {T.rub(amount)}"
        elif action == "paid":
            amount = await L.mark_prepayment_paid(order_id, actor)
            note = f"💰 Предоплата {T.rub(amount)} отмечена полученной"
        elif action == "start":
            n = await L.start_shift(order_id, actor)
            note = f"▶️ Смена начата, уведомлены {n} работников"
        elif action == "complete":
            n = await L.complete_shift(order_id, actor)
            note = f"🏁 Смена завершена ({n} работников), работодатель получил запрос оценки"
        elif action == "close":
            await L.close_order(order_id, actor)
            note = "✅ Расчёт закрыт"
        else:
            await callback.answer()
            return
    except L.LifecycleError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await _show_card(callback.message, order_id, edit=True, header=note)
    await callback.answer("Готово")


async def _show_responses(callback: CallbackQuery, order_id: int):
    async with async_session() as session:
        responses = await L.order_responses(session, order_id)
    if not responses:
        await callback.answer("Откликов пока нет", show_alert=True)
        return
    await callback.answer()
    for r in responses[:30]:
        w = r.worker
        text = (
            f"#{order_id} · {T.worker_name(w)} · ⭐️ {w.rating_display} · смен: {w.completed_shifts}\n"
            f"📊 {RESPONSE_STATUS_NAMES.get(r.status, r.status)}"
        )
        markup = (inline.get_response_actions_keyboard(r.id)
                  if r.status in (ResponseStatus.PENDING, ResponseStatus.CONTACTED) else None)
        if r.status == ResponseStatus.CONFIRMED:
            markup = to_markup([[("❌ Снять со смены", f"reject_response:{r.id}"),
                                 ("💬 Связаться", f"contact_worker:{r.id}")]])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)


# ==== Команды администратора ====

@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with async_session() as session:
        pending_employers = await EmployerService.get_pending_employers(session)
        counts = {}
        for status in ACTIVE_STATUSES:
            counts[status] = len(await OrderService.get_orders_by_status(session, status))
    text = (
        "👨‍💼 <b>Админ-панель СМЕНА</b>\n\n"
        f"• Работодателей на проверке: {len(pending_employers)}\n"
        f"• Заявок на модерации: {counts[OrderStatus.CREATED] + counts[OrderStatus.MODERATION]}\n"
        f"• В поиске работников: {counts[OrderStatus.SEARCH_WORKERS]}\n"
        f"• Набор закрыт: {counts[OrderStatus.CONFIRM_WORKERS]}\n"
        f"• Ждут предоплату: {counts[OrderStatus.PREPAYMENT]}\n"
        f"• Смена идёт: {counts[OrderStatus.SHIFT_STARTED]}\n"
        f"• Ждут закрытия расчёта: {counts[OrderStatus.SHIFT_COMPLETED]}\n\n"
        "<b>Команды</b>\n"
        "/orders — активные заказы с кнопками\n"
        "/order &lt;номер&gt; — карточка заказа и следующие шаги\n"
        "/complete &lt;номер&gt; — завершить смену и запросить оценки\n\n"
        "Все шаги синхронизированы с веб-панелью."
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("orders"))
async def admin_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with async_session() as session:
        orders = list((await session.execute(
            select(Order).where(Order.status.in_(ACTIVE_STATUSES)).order_by(Order.shift_date)
        )).scalars().all())
        lines = []
        for o in orders[:40]:
            c = await L.confirmed_count(session, o.id)
            lines.append((o.id, f"{T.STATUS_EMOJI.get(o.status, '')} {T.short_order(o)} · {c}/{o.workers_needed}"))
    if not lines:
        await message.answer("Активных заказов нет 🎉")
        return
    rows = [[(text, f"ao:card:{oid}")] for oid, text in lines]
    await message.answer(f"📋 <b>Активные заказы</b> ({len(lines)}), по дате смены:",
                         parse_mode="HTML", reply_markup=to_markup(rows))


@router.message(Command("order"))
async def admin_order(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        await message.answer("Использование: /order <номер заявки>")
        return
    await _show_card(message, int(arg))


@router.message(Command("complete"))
async def complete_shift(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        await message.answer("Использование: /complete <номер заявки>")
        return
    order_id = int(arg)
    try:
        n = await L.complete_shift(order_id, actor_name(message.from_user))
    except L.LifecycleError as e:
        await message.answer(f"❌ Заявка #{order_id}: {e}")
        return
    await message.answer(
        f"✅ Смена по заявке #{order_id} завершена. Работников: {n}. "
        "Работодателю отправлен запрос на оценку."
    )
