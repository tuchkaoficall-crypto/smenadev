"""Надёжность: штрафные баллы, уровни, приоритетная рассылка вакансий, ограничение откликов"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from config import OrderStatus, PENALTY_RESTRICT_POINTS
from database import async_session
from database.models import WorkerPenalty, Response
from services import reliability as R
from services import vacancy as V
from bot.utils import lifecycle as L
from bot.utils import scheduler
from tests.conftest import make_employer, make_worker, make_order, feed, callback_update


def _w(wid, **kw):
    base = dict(id=wid, user_id=wid, city="Петрозаводск", categories="[]", rating=0, total_reviews=0,
                completed_shifts=0, verified_at=None, user=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_levels_and_withdraw_rules():
    assert R.level(0)["code"] == "good"
    assert R.level(2)["code"] == "warn"
    assert R.level(5)["code"] == "low"
    assert R.level(PENALTY_RESTRICT_POINTS)["code"] == "restricted"
    assert R.penalty_for_withdraw(48) is None
    assert R.penalty_for_withdraw(23) == ("late_cancel", 2)
    assert R.penalty_for_withdraw(1) == ("very_late_cancel", 3)


def test_priority_rules_and_split():
    verified = _w(1, verified_at=datetime.now())
    top = _w(2, rating=4.8, total_reviews=3)
    newbie = _w(3)
    penalized = _w(4, verified_at=datetime.now())
    banned = _w(5)
    points = {4: 2, 5: PENALTY_RESTRICT_POINTS}
    priority, rest, restricted = R.split_recipients([newbie, top, verified, penalized, banned], points)
    assert [w.id for w in priority] == [1, 2]   # проверенный выше
    assert [w.id for w in rest] == [3, 4]       # без штрафов выше
    assert [w.id for w in restricted] == [5]


def test_vacancy_plan_stages():
    order = SimpleNamespace(id=1, city="Петрозаводск", category="Грузчик")
    ws = [_w(1, verified_at=datetime.now()), _w(2), _w(3, city="Кондопога")]
    targets, prio, events = V.plan(order, ws, {}, stage="first", delay_minutes=15)
    assert [w.id for w in targets] == [1] and events == [V.EV_PRIORITY]
    targets, _, events = V.plan(order, ws, {}, sent_user_ids={1}, stage="rest", delay_minutes=15)
    assert [w.id for w in targets] == [2] and events == [V.EV_REST]
    targets, _, events = V.plan(order, ws, {}, stage="first", delay_minutes=0)
    assert [w.id for w in targets] == [1, 2] and events == [V.EV_PRIORITY, V.EV_REST]


async def test_priority_broadcast_then_rest(outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        await make_worker(s, 2001, verified_at=datetime.utcnow())
        await make_worker(s, 2002, rating=4.9, total_reviews=2)
        await make_worker(s, 2003)
        bad = await make_worker(s, 2004)
        s.add(WorkerPenalty(worker_id=bad.id, kind="no_show", points=PENALTY_RESTRICT_POINTS))
        await s.commit()
        order = await make_order(s, emp, status=OrderStatus.CREATED)

    assert await L.approve_order(order.id, "admin") == 2
    assert outbox.to(2001) and "раньше других" in outbox.to(2001)[0]
    assert outbox.to(2002) and not outbox.to(2003)

    assert await scheduler.run_vacancy_rest() == 0  # задержка ещё не прошла
    later = datetime.utcnow() + timedelta(minutes=16)
    assert await scheduler.run_vacancy_rest(later) == 1
    assert outbox.to(2003) and "раньше других" not in outbox.to(2003)[0]
    assert not outbox.to(2004)  # ограниченный не получает вакансии
    assert await scheduler.run_vacancy_rest(later) == 0
    assert len(outbox.to(2001)) == 1  # без повторов


async def test_old_orders_not_rebroadcast(outbox):
    """Заказы, одобренные до обновления (нет события broadcast_priority), повторно не рассылаются"""
    async with async_session() as s:
        emp = await make_employer(s)
        await make_worker(s, 2001)
        await make_order(s, emp, moderated_at=datetime.utcnow() - timedelta(days=1))
    assert await scheduler.run_vacancy_rest() == 0
    assert not outbox.to(2001)


async def test_restricted_worker_cannot_respond(dp, outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001)
        s.add(WorkerPenalty(worker_id=w.id, kind="no_show", points=12))
        await s.commit()
        order = await make_order(s, emp)
    await feed(dp, callback_update(2001, f"respond:{order.id}"))
    assert any("штрафных баллов" in (t or "") for t in outbox.answers())
    async with async_session() as s:
        assert not list((await s.execute(select(Response))).scalars())


async def test_normal_worker_can_respond(dp, outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        await make_worker(s, 2001)
        order = await make_order(s, emp)
    await feed(dp, callback_update(2001, f"respond:{order.id}"))
    async with async_session() as s:
        assert len(list((await s.execute(select(Response))).scalars())) == 1
    assert any("Новый отклик" in t and "Надёжный" in t for t in outbox.to(999))


async def test_expired_penalties_ignored():
    async with async_session() as s:
        w = await make_worker(s, 2001)
        s.add(WorkerPenalty(worker_id=w.id, kind="no_show", points=5,
                            created_at=datetime.utcnow() - timedelta(days=200)))
        s.add(WorkerPenalty(worker_id=w.id, kind="late_cancel", points=2))
        s.add(WorkerPenalty(worker_id=w.id, kind="late_cancel", points=2, is_cancelled=True))
        await s.commit()
        assert await R.worker_points_async(s, w.id) == 2
