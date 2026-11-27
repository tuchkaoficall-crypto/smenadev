"""
Дополнительные функции работника:
  • «📍 Я на месте» с геолокацией (bot/utils/checkin.py);
  • загрузка документов на проверку (паспорт, медкнижка), решение принимает админ в веб-панели;
  • смена города (список городов редактируется в админке);
  • просмотр штрафных баллов и уровня надёжности.
"""
import logging
from html import escape

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy import select

from config import (
    DOCUMENT_TYPES, DOCUMENT_STATUS_NAMES, PENALTY_NAMES, PENALTY_RESTRICT_POINTS, PENALTY_WINDOW_DAYS,
    ADMIN_CONTACT,
)
from database import async_session
from database.models import WorkerDocument, WorkerPenalty
from services import WorkerService
from services import reliability as R
from services.cities import is_active as is_active_city
from bot.keyboards import reply, inline
from bot.keyboards.lifecycle import to_markup
from bot.states import CheckIn, DocUpload
from bot.utils import checkin as C

router = Router()
logger = logging.getLogger(__name__)

NO_GEO = "📍 Отметиться без геолокации"
MAX_PENDING_DOCS = 5


def profile_markup(worker, points: int):
    rows = []
    if not worker.verified_at:
        rows.append([("🪪 Подтвердить документы", "wp:docs")])
    else:
        rows.append([("🪪 Мои документы", "wp:docs")])
    rows.append([("📍 Сменить город", "wp:city"), (f"⚠️ Баллы: {points}", "wp:points")])
    return to_markup(rows)


# ==== Отметка «я на месте» ====

def _location_keyboard():
    b = ReplyKeyboardBuilder()
    b.button(text="📍 Отправить геолокацию", request_location=True)
    b.button(text=NO_GEO)
    b.button(text="❌ Отмена")
    b.adjust(1)
    return b.as_markup(resize_keyboard=True, one_time_keyboard=True)


@router.callback_query(F.data.regexp(r"^wr:checkin:\d+$"))
async def checkin_start(callback: CallbackQuery, state: FSMContext):
    response_id = int(callback.data.split(":")[2])
    try:
        response = await C.validate(response_id, callback.from_user.id)
    except C.CheckinError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await state.set_state(CheckIn.location)
    await state.update_data(checkin_response=response_id)
    await callback.message.answer(
        f"📍 Отметка на смене #{response.order_id}\n\n"
        "Нажмите «📍 Отправить геолокацию» внизу экрана: так работодатель увидит, что вы на месте. "
        "Если геолокация не отправляется, отметьтесь без неё.",
        reply_markup=_location_keyboard(),
    )
    await callback.answer()


async def _finish_checkin(message: Message, state: FSMContext, lat=None, lon=None):
    data = await state.get_data()
    response_id = data.get("checkin_response")
    await state.clear()
    if not response_id:
        await message.answer("Нажмите «📍 Я на месте» в сообщении о смене ещё раз.",
                             reply_markup=reply.get_worker_menu())
        return
    try:
        result = await C.record_checkin(response_id, message.from_user.id, lat, lon)
    except C.CheckinError as e:
        await message.answer(f"❌ {e}", reply_markup=reply.get_worker_menu())
        return
    text = "✅ Отметка принята, работодатель получил уведомление. Хорошей смены!"
    if result["penalty"]:
        text += f"\n⏰ Опоздание {result['late']} мин."
    if result["distance"] is not None and result["distance"] > 500:
        text += (f"\n⚠️ Вы в {result['distance']} м от адреса смены ({escape(result['address'])}). "
                 "Если вы на месте, ничего делать не нужно.")
    await message.answer(text, reply_markup=reply.get_worker_menu())


@router.message(CheckIn.location, F.location)
async def checkin_location(message: Message, state: FSMContext):
    await _finish_checkin(message, state, message.location.latitude, message.location.longitude)


@router.message(CheckIn.location, F.text == NO_GEO)
async def checkin_no_geo(message: Message, state: FSMContext):
    await _finish_checkin(message, state)


@router.message(CheckIn.location)
async def checkin_other(message: Message):
    await message.answer("Отправьте геолокацию кнопкой внизу или нажмите «Отметиться без геолокации».",
                         reply_markup=_location_keyboard())


# ==== Документы ====

@router.callback_query(F.data == "wp:docs")
async def docs_menu(callback: CallbackQuery):
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, callback.from_user.id)
        if not worker:
            await callback.answer("Сначала пройдите регистрацию", show_alert=True)
            return
        docs = list((await session.execute(select(WorkerDocument).where(
            WorkerDocument.worker_id == worker.id).order_by(WorkerDocument.created_at.desc()))).scalars().all())
        verified = worker.verified_at
    lines = ["🪪 <b>Проверка документов</b>\n"]
    if verified:
        lines.append("✅ Паспорт проверен. Вы получаете вакансии в числе первых.\n")
    else:
        lines.append("Загрузите фото паспорта (разворот с фото). После проверки администратором "
                     "в профиле появится отметка «Документы проверены», а вакансии будут "
                     "приходить вам раньше других. Данные видит только администратор.\n")
    for d in docs[:8]:
        status = DOCUMENT_STATUS_NAMES.get(d.status, d.status)
        line = f"• {DOCUMENT_TYPES.get(d.doc_type, d.doc_type)}: {status} ({d.created_at.strftime('%d.%m')})"
        if d.status == "rejected" and d.reject_reason:
            line += f"\n   Причина: {escape(d.reject_reason)}"
        lines.append(line)
    rows = [[(f"📤 {name}", f"wd:type:{code}")] for code, name in DOCUMENT_TYPES.items()]
    await callback.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=to_markup(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("wd:type:"))
async def docs_choose(callback: CallbackQuery, state: FSMContext):
    doc_type = callback.data.split(":")[2]
    if doc_type not in DOCUMENT_TYPES:
        await callback.answer()
        return
    await state.set_state(DocUpload.file)
    await state.update_data(doc_type=doc_type)
    await callback.message.answer(
        f"📤 Отправьте фото или файл: <b>{DOCUMENT_TYPES[doc_type]}</b>.\n"
        "Снимок должен быть чётким, без бликов. Для отмены нажмите «❌ Отмена».",
        parse_mode="HTML", reply_markup=reply.get_cancel_keyboard(),
    )
    await callback.answer()


@router.message(DocUpload.file, F.photo | F.document)
async def docs_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    doc_type = data.get("doc_type", "other")
    if message.photo:
        file_id, kind, name, mime = message.photo[-1].file_id, "photo", None, "image/jpeg"
    else:
        doc = message.document
        if doc.file_size and doc.file_size > 10 * 1024 * 1024:
            await message.answer("❌ Файл больше 10 МБ, отправьте фото поменьше.")
            return
        file_id, kind, name, mime = doc.file_id, "document", doc.file_name, doc.mime_type
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, message.from_user.id)
        if not worker:
            await state.clear()
            await message.answer("Сначала пройдите регистрацию: /start")
            return
        pending = (await session.execute(select(WorkerDocument.id).where(
            WorkerDocument.worker_id == worker.id, WorkerDocument.status == "pending"))).all()
        if len(pending) >= MAX_PENDING_DOCS:
            await state.clear()
            await message.answer("У вас уже несколько документов на проверке, дождитесь решения администратора.",
                                 reply_markup=reply.get_worker_menu())
            return
        doc = WorkerDocument(worker_id=worker.id, doc_type=doc_type, file_id=file_id, file_kind=kind,
                             file_name=name, mime_type=mime, status="pending")
        session.add(doc)
        await session.commit()
        doc_id, worker_name = doc.id, worker.user.full_name if worker.user else str(worker.user_id)
        worker_id = worker.id
    await state.clear()
    await message.answer("✅ Документ отправлен на проверку. Мы сообщим о решении.",
                         reply_markup=reply.get_worker_menu())
    from bot.utils.lifecycle import send_admins
    await send_admins(f"🪪 <b>Новый документ на проверке</b> #{doc_id}\n"
                      f"Работник: {escape(worker_name)} (ID {worker_id})\n"
                      f"Тип: {DOCUMENT_TYPES.get(doc_type, doc_type)}\n\n"
                      "Проверьте в веб-панели: «Модерация» или карточка работника.")


@router.message(DocUpload.file)
async def docs_wrong(message: Message):
    await message.answer("Пришлите фото или файл документа, либо нажмите «❌ Отмена».")


# ==== Город ====

@router.callback_query(F.data == "wp:city")
async def city_menu(callback: CallbackQuery):
    await callback.message.answer("📍 Выберите город, в котором ищете работу:",
                                  reply_markup=inline.get_cities_keyboard(prefix="wcity:"))
    await callback.answer()


@router.callback_query(F.data.startswith("wcity:"))
async def city_set(callback: CallbackQuery):
    city = callback.data.split(":", 1)[1]
    if not is_active_city(city):
        await callback.answer("Этот город сейчас недоступен", show_alert=True)
        return
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, callback.from_user.id)
        if not worker:
            await callback.answer("Сначала пройдите регистрацию", show_alert=True)
            return
        worker.city = city
        await session.commit()
    await callback.message.edit_text(f"✅ Город изменён: <b>{escape(city)}</b>. "
                                     "Теперь вы будете получать вакансии этого города.", parse_mode="HTML")
    await callback.answer()


# ==== Баллы ====

@router.callback_query(F.data == "wp:points")
async def points_info(callback: CallbackQuery):
    async with async_session() as session:
        worker = await WorkerService.get_worker(session, callback.from_user.id)
        if not worker:
            await callback.answer()
            return
        points = await R.worker_points_async(session, worker.id)
        items = list((await session.execute(select(WorkerPenalty).where(
            WorkerPenalty.worker_id == worker.id, WorkerPenalty.is_cancelled.is_(False),
            WorkerPenalty.created_at >= R.window_start(),
        ).order_by(WorkerPenalty.created_at.desc()))).scalars().all())
    lvl = R.level(points)
    lines = [
        f"{lvl['emoji']} <b>Надёжность: {lvl['label']}</b>",
        f"Штрафных баллов за {PENALTY_WINDOW_DAYS} дней: <b>{points}</b> "
        f"(при {PENALTY_RESTRICT_POINTS} вакансии перестают приходить)\n",
        "Как начисляются баллы:",
        "• отказ от смены менее чем за 24 ч: +2, менее чем за 3 ч: +3",
        "• неявка без предупреждения: +5",
        "• опоздание больше 15 минут: +1",
        "Работники без баллов с хорошим рейтингом или проверенными документами получают вакансии первыми.",
    ]
    if items:
        lines.append("\n<b>Ваши баллы:</b>")
        for p in items[:10]:
            lines.append(f"• {p.created_at.strftime('%d.%m')} +{p.points}: {PENALTY_NAMES.get(p.kind, p.kind)}"
                         + (f" (смена #{p.order_id})" if p.order_id else ""))
    lines.append(f"\nНе согласны? Напишите {ADMIN_CONTACT}")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()

