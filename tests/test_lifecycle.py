"""Жизненный цикл заказа в боте: от модерации до закрытия расчёта"""
import pytest
from sqlalchemy import select

from config import OrderStatus, ResponseStatus
from database import async_session
from database.models import Order, Response, Worker, Payment, WorkerPenalty, AdminAction
from bot.utils import lifecycle as L
from tests.conftest import make_employer, make_worker, make_order, make_response, ADMIN_ID


async def _reload(model, obj_id):
    async with async_session() as s:
        return await s.get(model, obj_id)


async def test_full_happy_path(outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        w1 = await make_worker(s, 2001, categories=["Грузчик"])
        w2 = await make_worker(s, 2002)                      # «любая работа»
        await make_worker(s, 2003, categories=["Курьер"])  # не подходит по категории
        await make_worker(s, 2004, city="Кондопога")       # другой город
        order = await make_order(s, emp, status=OrderStatus.CREATED, workers_needed=2)

    # Модерация: приоритетных нет, поэтому вакансия сразу уходит всем подходящим
    sent = await L.approve_order(order.id, "admin")
    assert sent == 2
    assert (await _reload(Order, order.id)).status == OrderStatus.SEARCH_WORKERS
    assert any("одобрена" in t for t in outbox.to(1000))
    assert outbox.to(2001) and outbox.to(2002)
    assert not outbox.to(2003) and not outbox.to(2004)

    async with async_session() as s:
        r1 = await make_response(s, order, w1)
        r2 = await make_response(s, order, w2)

    confirmed, needed, filled = await L.confirm_response(r1.id, "admin")
    assert (confirmed, needed, filled) == (1, 2, False)
    confirmed, needed, filled = await L.confirm_response(r2.id, "admin")
    assert filled and (await _reload(Order, order.id)).status == OrderStatus.CONFIRM_WORKERS
    assert any("подтверждены на смену" in t for t in outbox.to(2001))
    with pytest.raises(L.LifecycleError):
        await L.confirm_response(r2.id, "admin")

    amount = await L.request_prepayment(order.id, "admin")
    assert amount == 300
    await L.employer_reports_paid(order.id, 1000)
    assert any("оплатил предоплату" in t for t in outbox.to(ADMIN_ID))
    assert await L.mark_prepayment_paid(order.id, "admin") == 300

    assert await L.start_shift(order.id, "admin") == 2
    assert await L.complete_shift(order.id, "employer", by_employer_user=1000) == 2
    o = await _reload(Order, order.id)
    assert o.status == OrderStatus.SHIFT_COMPLETED and o.completed_at
    assert (await _reload(Worker, w1.id)).completed_shifts == 1
    assert (await _reload(Response, r1.id)).status == ResponseStatus.COMPLETED

    await L.close_order(order.id, "admin")
    o = await _reload(Order, order.id)
    assert o.status == OrderStatus.PAYMENT_COMPLETED
    async with async_session() as s:
        payments = list((await s.execute(select(Payment).where(Payment.order_id == order.id))).scalars())
        log = list((await s.execute(select(AdminAction.action).where(AdminAction.entity_id == order.id))).scalars())
    assert sum(p.amount for p in payments if p.status == "completed") == pytest.approx(600)
    assert {"order_approve", "response_confirm", "order_start", "order_complete", "order_close"} <= set(log)


async def test_withdraw_early_reopens_without_penalty(outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001)
        order = await make_order(s, emp, hours_ahead=48, workers_needed=1, status=OrderStatus.CONFIRM_WORKERS)
        r = await make_response(s, order, w, status=ResponseStatus.CONFIRMED)

    assert await L.withdraw_response(r.id, 2001) is True
    assert (await _reload(Order, order.id)).status == OrderStatus.SEARCH_WORKERS
    async with async_session() as s:
        assert not list((await s.execute(select(WorkerPenalty))).scalars())
    assert any("отказался" in t for t in outbox.to(1000))


@pytest.mark.parametrize("hours, kind, points", [(10, "late_cancel", 2), (2, "very_late_cancel", 3)])
async def test_late_withdraw_gives_penalty(outbox, hours, kind, points):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001)
        order = await make_order(s, emp, hours_ahead=hours, workers_needed=1, status=OrderStatus.CONFIRM_WORKERS)
        r = await make_response(s, order, w, status=ResponseStatus.CONFIRMED)

    await L.withdraw_response(r.id, 2001)
    async with async_session() as s:
        pens = list((await s.execute(select(WorkerPenalty))).scalars())
    assert [(p.kind, p.points) for p in pens] == [(kind, points)]
    assert any("штрафные баллы" in t for t in outbox.to(2001))
    assert any("СРОЧНО" in t for t in outbox.to(ADMIN_ID))


async def test_employer_cannot_cancel_with_confirmed_workers(outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001)
        order = await make_order(s, emp)
        await make_response(s, order, w, status=ResponseStatus.CONFIRMED)
    with pytest.raises(L.LifecycleError):
        await L.cancel_order(order.id, "передумали", "employer", by_employer_user=1000)
    await L.cancel_order(order.id, "передумали", "admin")
    assert (await _reload(Order, order.id)).status == OrderStatus.CANCELLED
    assert any("отменена" in t for t in outbox.to(2001))


async def test_withdraw_foreign_response_rejected():
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001)
        order = await make_order(s, emp)
        r = await make_response(s, order, w)
    with pytest.raises(L.LifecycleError):
        await L.withdraw_response(r.id, 5555)
