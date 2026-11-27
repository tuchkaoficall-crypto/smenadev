"""Веб-админка: документы, неявки, штрафы, отметки, рефералы, города (Flask test client)"""
from datetime import datetime, timedelta

import pytest

from config import OrderStatus, ResponseStatus
from database import async_session
from database.models import (
    Worker, Response, WorkerPenalty, WorkerDocument, Referral, City, Order, ShiftCheckin,
)
from tests.conftest import make_employer, make_worker, make_order, make_response


@pytest.fixture
def client(outbox):
    from admin import app, db_session
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    r = c.post("/auth/login", data={"username": "tester", "password": "tester-pass", "csrf_token": "tok"})
    assert r.status_code == 302
    yield c
    db_session.remove()


def post(client, url, **data):
    return client.post(url, data={"csrf_token": "tok", **data})


def get_db():
    from admin import db_session
    db_session.expire_all()
    return db_session


async def test_pages_render_with_data(client):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001, verified_at=datetime.utcnow())
        order = await make_order(s, emp, hours_ahead=-1, status=OrderStatus.SHIFT_STARTED,
                                 latitude=61.78, longitude=34.35)
        r = await make_response(s, order, w, status=ResponseStatus.CONFIRMED)
        s.add(ShiftCheckin(order_id=order.id, response_id=r.id, worker_id=w.id, latitude=61.78,
                           longitude=34.35, distance_m=12, late_minutes=3))
        s.add(WorkerPenalty(worker_id=w.id, kind="late_cancel", points=2))
        s.add(WorkerDocument(worker_id=w.id, file_id="F", doc_type="medbook"))
        s.add(Referral(referrer_id=2001, referred_id=1000, status="qualified", bonus_amount=300))
        await s.commit()
    for url in ["/dashboard/", "/moderation/", "/workers/", "/workers/?reliability=warn&verified=1",
                f"/workers/{w.id}", f"/orders/{order.id}", "/referrals/", "/referrals/?status=qualified",
                "/cities/", "/broadcasts/", "/orders/", "/workers/export.csv", "/referrals/export.csv"]:
        resp = client.get(url)
        assert resp.status_code == 200, url
    detail = client.get(f"/orders/{order.id}").get_data(as_text=True)
    assert "+3 мин" in detail and "12 м" in detail
    worker_page = client.get(f"/workers/{w.id}").get_data(as_text=True)
    assert "документы проверены" in worker_page and "Есть замечания" in worker_page
    assert "Медицинская книжка" in client.get("/moderation/").get_data(as_text=True)


async def test_document_approve_sets_verified(client, outbox):
    async with async_session() as s:
        w = await make_worker(s, 2001)
        s.add(WorkerDocument(worker_id=w.id, file_id="F1", doc_type="passport"))
        await s.commit()
    doc_id = get_db().query(WorkerDocument).one().id
    resp = post(client, f"/workers/documents/{doc_id}/approve")
    assert resp.status_code == 302
    db = get_db()
    assert db.query(WorkerDocument).one().status == "approved"
    assert db.get(Worker, w.id).verified_at is not None
    assert any("проверен" in t for t in outbox.to(2001))


async def test_document_reject_with_reason(client, outbox):
    async with async_session() as s:
        w = await make_worker(s, 2001)
        s.add(WorkerDocument(worker_id=w.id, file_id="F1", doc_type="passport"))
        await s.commit()
    doc_id = get_db().query(WorkerDocument).one().id
    post(client, f"/workers/documents/{doc_id}/reject", reason="Размыто")
    db = get_db()
    assert db.query(WorkerDocument).one().reject_reason == "Размыто"
    assert db.get(Worker, w.id).verified_at is None
    assert any("Размыто" in t for t in outbox.to(2001))


async def test_no_show_marks_penalty(client, outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        w = await make_worker(s, 2001, completed_shifts=3)
        order = await make_order(s, emp, hours_ahead=-3, status=OrderStatus.SHIFT_COMPLETED)
        r = await make_response(s, order, w, status=ResponseStatus.COMPLETED)
        future = await make_order(s, emp, hours_ahead=10)
        r2 = await make_response(s, future, w, status=ResponseStatus.CONFIRMED)
    post(client, f"/orders/responses/{r.id}/noshow")
    db = get_db()
    assert db.get(Response, r.id).status == ResponseStatus.NO_SHOW
    assert db.get(Worker, w.id).completed_shifts == 2
    pen = db.query(WorkerPenalty).one()
    assert (pen.kind, pen.points) == ("no_show", 5)
    assert any("Неявка" in t for t in outbox.to(2001))
    # Будущую смену отметить неявкой нельзя
    post(client, f"/orders/responses/{r2.id}/noshow")
    assert get_db().get(Response, r2.id).status == ResponseStatus.CONFIRMED


async def test_manual_penalty_and_cancel(client, outbox):
    async with async_session() as s:
        w = await make_worker(s, 2001)
    post(client, f"/workers/{w.id}/penalty", kind="manual", points="4", reason="грубость", notify="1")
    pen = get_db().query(WorkerPenalty).one()
    assert pen.points == 4 and pen.reason == "грубость"
    pen_id = pen.id
    post(client, f"/workers/penalties/{pen_id}/cancel")
    assert get_db().query(WorkerPenalty).one().is_cancelled
    assert any("аннулировал" in t for t in outbox.to(2001))


async def test_order_point(client):
    async with async_session() as s:
        emp = await make_employer(s)
        order = await make_order(s, emp)
    post(client, f"/orders/{order.id}/point", point="61.7849, 34.3469")
    o = get_db().get(Order, order.id)
    assert (round(o.latitude, 4), round(o.longitude, 4)) == (61.7849, 34.3469)
    post(client, f"/orders/{order.id}/point", point="https://yandex.ru/maps/?pt=34.35,61.78&z=17")
    o = get_db().get(Order, order.id)
    assert (o.latitude, o.longitude) == (61.78, 34.35)
    post(client, f"/orders/{order.id}/point", point="")
    assert get_db().get(Order, order.id).latitude is None


async def test_referral_mark_paid(client, outbox):
    async with async_session() as s:
        await make_worker(s, 2001)
        s.add(Referral(referrer_id=2001, referred_id=3001, status="invited"))
        s.add(Referral(referrer_id=2001, referred_id=3002, status="qualified", bonus_amount=300))
        await s.commit()
    refs = {r.referred_id: r.id for r in get_db().query(Referral).all()}
    post(client, f"/referrals/{refs[3001]}/paid")  # не начислен -> нельзя
    post(client, f"/referrals/{refs[3002]}/paid")
    db = get_db()
    assert db.get(Referral, refs[3001]).status == "invited"
    paid = db.get(Referral, refs[3002])
    assert paid.status == "paid" and paid.paid_at
    assert any("выплачен" in t for t in outbox.to(2001))


async def test_cities_admin(client):
    async with async_session() as s:
        await make_worker(s, 2001, city="Петрозаводск")
        emp = await make_employer(s)
        await make_order(s, emp, city="Петрозаводск")
    post(client, "/cities/add", name="  Кондопога ")
    db = get_db()
    assert [c.name for c in db.query(City).order_by(City.sort_order)] == ["Петрозаводск", "Кондопога"]
    post(client, "/cities/add", name="Кондопога")  # дубль не создаётся
    assert get_db().query(City).count() == 2

    ptz = get_db().query(City).filter(City.name == "Петрозаводск").one().id
    post(client, f"/cities/{ptz}/rename", name="г. Петрозаводск")
    db = get_db()
    assert db.query(Worker).one().city == "г. Петрозаводск"
    assert db.query(Order).one().city == "г. Петрозаводск"

    kon = db.query(City).filter(City.name == "Кондопога").one().id
    post(client, f"/cities/{kon}/toggle")
    assert get_db().get(City, kon).is_active is False
    post(client, f"/cities/{ptz}/toggle")  # последний активный выключить нельзя
    assert get_db().get(City, ptz).is_active is True
    post(client, f"/cities/{kon}/move/up")
    assert get_db().query(City).order_by(City.sort_order).first().name == "Кондопога"


async def test_admin_approve_uses_priority_broadcast(client, outbox):
    async with async_session() as s:
        emp = await make_employer(s)
        await make_worker(s, 2001, verified_at=datetime.utcnow())
        await make_worker(s, 2002)
        order = await make_order(s, emp, status=OrderStatus.CREATED)
    post(client, f"/orders/{order.id}/approve")
    assert outbox.to(2001) and not outbox.to(2002)
    from bot.utils import scheduler
    assert await scheduler.run_vacancy_rest(datetime.utcnow() + timedelta(minutes=20)) == 1
    assert outbox.to(2002)
