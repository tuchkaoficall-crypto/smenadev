"""Напоминания о смене (24 ч / 2 ч) и отметка «я на месте» с геолокацией"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from config import OrderStatus, ResponseStatus
from database import async_session
from database.models import ShiftCheckin, WorkerPenalty, Order
from bot.utils import scheduler, checkin as C
from tests.conftest import (
    make_employer, make_worker, make_order, make_response, ADMIN_ID, feed, callback_update, message_update,
)


async def _setup(hours_ahead, **order_fields):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001, name="Олег Иванов")
        order = await make_order(s, emp, hours_ahead=hours_ahead, workers_needed=1,
                                 status=OrderStatus.CONFIRM_WORKERS, **order_fields)
        r = await make_response(s, order, w, status=ResponseStatus.CONFIRMED)
    return emp, w, order, r


async def test_24h_and_2h_reminders_sent_once(outbox):
    _, _, order, r = await _setup(hours_ahead=20)
    await scheduler.run_reminders()
    worker_msgs = outbox.to(2001)
    assert len(worker_msgs) == 1 and "Напоминание" in worker_msgs[0]
    assert f"wr:attend:{r.id}" in outbox.buttons_to(2001)
    assert any("Подтверждено работников" in t for t in outbox.to(1000))

    await scheduler.run_reminders()  # повторный проход ничего не шлёт
    assert len(outbox.to(2001)) == 1

    # За 2 часа — второе напоминание
    await scheduler.run_reminders(now=order.shift_date - timedelta(hours=1, minutes=50))
    assert len(outbox.to(2001)) == 2
    assert any("Я на месте" in t for t in outbox.to(1000))  # работодателю за 2 часа


async def test_checkin_prompt_and_missing_alert(outbox):
    _, _, order, r = await _setup(hours_ahead=0.4)  # смена через 24 минуты
    await scheduler.run_reminders()
    assert f"wr:checkin:{r.id}" in outbox.buttons_to(2001)
    prompts = [t for t in outbox.to(2001) if "Я на месте" in t]
    assert len(prompts) == 1

    # Через 20 минут после начала никто не отметился -> работодателю и админам
    await scheduler.run_reminders(now=order.shift_date + timedelta(minutes=20))
    assert any("ещё не отметились" in t and "Олег" in t for t in outbox.to(1000))
    assert any("ещё не отметились" in t for t in outbox.to(ADMIN_ID))
    n = len(outbox.to(1000))
    await scheduler.run_reminders(now=order.shift_date + timedelta(minutes=25))
    assert len(outbox.to(1000)) == n


async def test_record_checkin_with_location_and_distance(outbox):
    _, w, order, r = await _setup(hours_ahead=0.2, latitude=61.7849, longitude=34.3469)
    res = await C.record_checkin(r.id, 2001, 61.7858, 34.3469)  # ~100 м севернее
    assert 80 <= res["distance"] <= 120 and res["penalty"] == 0
    assert any("на месте" in t and "м от точки" in t for t in outbox.to(1000))
    assert any("На месте: 1 из 1" in t for t in outbox.to(ADMIN_ID))
    with pytest.raises(C.CheckinError):
        await C.record_checkin(r.id, 2001, 61.7858, 34.3469)


async def test_late_checkin_penalty_and_window(outbox):
    _, w, order, r = await _setup(hours_ahead=5)
    with pytest.raises(C.CheckinError, match="не раньше"):
        await C.record_checkin(r.id, 2001)
    res = await C.record_checkin(r.id, 2001, now=order.shift_date + timedelta(minutes=40))
    assert res["late"] == 40 and res["penalty"] == 1
    async with async_session() as s:
        c = (await s.execute(select(ShiftCheckin))).scalar_one()
        p = (await s.execute(select(WorkerPenalty))).scalar_one()
    assert c.latitude is None and c.late_minutes == 40 and p.kind == "late_checkin"
    assert any("опоздание 40 мин" in t for t in outbox.to(1000))


async def test_checkin_via_bot_with_geolocation(dp, outbox):
    _, w, order, r = await _setup(hours_ahead=0.3)
    await feed(dp, callback_update(2001, f"wr:checkin:{r.id}"))
    assert any("Отправить геолокацию" in t or "геолокацию" in t for t in outbox.to(2001))
    await feed(dp, message_update(2001, location={"latitude": 61.78, "longitude": 34.35}))
    assert any("Отметка принята" in t for t in outbox.to(2001))
    async with async_session() as s:
        c = (await s.execute(select(ShiftCheckin))).scalar_one()
    assert c.latitude == pytest.approx(61.78) and c.response_id == r.id
    # Карточка работодателя показывает «на месте»
    async with async_session() as s:
        from bot.utils import lifecycle as L
        text, _ = await L.employer_card(s, await s.get(Order, order.id))
    assert "На месте: <b>1 из 1</b>" in text


async def test_checkin_rejected_for_other_user(dp, outbox):
    _, w, order, r = await _setup(hours_ahead=0.3)
    await feed(dp, callback_update(3333, f"wr:checkin:{r.id}"))
    assert "Смена не найдена" in outbox.answers()
