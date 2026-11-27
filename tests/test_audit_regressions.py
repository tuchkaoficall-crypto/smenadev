"""Regression coverage for recruitment guards and retryable reminders."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from config import OrderStatus, ResponseStatus
from database import async_session
from database.models import Response
from bot.utils import scheduler, lifecycle as L
from tests.conftest import make_employer, make_worker, make_order, make_response, ADMIN_ID
from tests.test_shift_reminders import _setup


@pytest.mark.parametrize("status", [
    OrderStatus.CREATED, OrderStatus.MODERATION, OrderStatus.SHIFT_STARTED,
    OrderStatus.SHIFT_COMPLETED, OrderStatus.PAYMENT_COMPLETED, OrderStatus.CANCELLED,
])
async def test_web_cannot_confirm_outside_recruitment(status, outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        worker = await make_worker(s, 2001)
        order = await make_order(s, emp, status=status)
        response = await make_response(s, order, worker)
        response_id = response.id
    from admin import app, db_session, services
    with app.app_context():
        response = db_session.get(Response, response_id)
        with pytest.raises(services.LifecycleError, match="набор"):
            services.confirm_response(response)
        assert response.status == ResponseStatus.PENDING
        assert response.confirmed_at is None
    assert not outbox.messages


@pytest.mark.parametrize("hours,kind", [
    (20, "remind_24h"), (1, "remind_2h"), (0.4, "checkin_prompt"),
])
async def test_worker_reminder_retries_failed_send(hours, kind, monkeypatch, outbox):
    _, _, order, _ = await _setup(hours_ahead=hours)
    real_send = L.send
    failed = False

    async def send(chat_id, text, rows=None):
        nonlocal failed
        is_target = "Я на месте" in text if kind == "checkin_prompt" else "Напоминание" in text
        if chat_id == 2001 and is_target and not failed:
            failed = True
            return False
        return await real_send(chat_id, text, rows)

    monkeypatch.setattr(L, "send", send)
    await scheduler.run_reminders()
    assert failed
    async with async_session() as s:
        assert not await L.has_event(s, order.id, "delivery:" + kind, 2001)
    await scheduler.run_reminders()
    async with async_session() as s:
        assert await L.has_event(s, order.id, "delivery:" + kind, 2001)
    count = len(outbox.to(2001))
    await scheduler.run_reminders()
    assert len(outbox.to(2001)) == count


async def test_admin_failure_does_not_repeat_employer_alert(monkeypatch, outbox):
    _, _, order, _ = await _setup(hours_ahead=0.4)
    now = order.shift_date + timedelta(minutes=20)
    real_send = L.send

    async def send(chat_id, text, rows=None):
        if chat_id == ADMIN_ID:
            return False
        return await real_send(chat_id, text, rows)

    monkeypatch.setattr(L, "send", send)
    await scheduler.run_reminders(now)
    employer_count = len(outbox.to(1000))
    assert employer_count
    assert not outbox.to(ADMIN_ID)
    monkeypatch.setattr(L, "send", real_send)
    await scheduler.run_reminders(now)
    assert len(outbox.to(1000)) == employer_count
    assert any("ещё не отметились" in text for text in outbox.to(ADMIN_ID))


async def test_old_event_prevents_resending(monkeypatch):
    _, _, order, _ = await _setup(hours_ahead=20)
    async with async_session() as s:
        await L.add_event(s, order.id, "remind_24h", 2001)
        send = AsyncMock(return_value=True)
        monkeypatch.setattr(L, "send", send)
        assert await scheduler._send_once(s, order.id, "remind_24h", 2001, "text",
                                          legacy_user_id=2001) == 0
        send.assert_not_awaited()
