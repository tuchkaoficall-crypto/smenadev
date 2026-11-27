"""Реферальная программа, документы, города и аддитивная миграция схемы"""
import os
import sqlite3
import tempfile

from sqlalchemy import select, create_engine, inspect

from config import OrderStatus
from database import async_session
from database.models import Referral, City, WorkerDocument
from services import cities
from bot.utils import referrals, scheduler
from tests.conftest import make_employer, make_worker, make_order, feed, message_update, callback_update


# ==== Рефералы ====

def test_parse_payload():
    assert referrals.parse_payload("/start ref_42") == 42
    assert referrals.parse_payload("/start") is None
    assert referrals.parse_payload("/start promo") is None
    assert referrals.parse_payload("/start ref_abc") is None


async def test_referral_flow_via_bot(dp, outbox):
    async with async_session() as s:
        await make_worker(s, 2001)
    await feed(dp, message_update(5001, "/start ref_2001"))
    async with async_session() as s:
        ref = (await s.execute(select(Referral))).scalar_one()
    assert (ref.referrer_id, ref.referred_id, ref.status) == (2001, 5001, "invited")
    assert any("По вашей ссылке" in t for t in outbox.to(2001))

    # Повторный /start и самоприглашение ничего не создают
    await feed(dp, message_update(5001, "/start ref_2001"))
    await feed(dp, message_update(2001, "/start ref_2001"))
    async with async_session() as s:
        assert len(list((await s.execute(select(Referral))).scalars())) == 1

    # Ссылка и статистика по кнопке меню
    await feed(dp, message_update(2001, "🎁 Пригласить друга"))
    assert any("t.me/smena_test_bot?start=ref_2001" in t for t in outbox.to(2001))


async def test_referral_qualifies_after_first_shift(outbox):
    async with async_session() as s:
        await make_worker(s, 2001)
        await make_worker(s, 2002, completed_shifts=0)
        s.add(Referral(referrer_id=2001, referred_id=2002, status="invited"))
        await s.commit()
    assert await referrals.run_referrals() == 0

    async with async_session() as s:
        from database.models import Worker
        w = (await s.execute(select(Worker).where(Worker.user_id == 2002))).scalar_one()
        w.completed_shifts = 1
        await s.commit()
    assert await scheduler.run_background() >= 1
    async with async_session() as s:
        ref = (await s.execute(select(Referral))).scalar_one()
    assert ref.status == "qualified" and ref.bonus_amount == 300 and ref.role == "worker"
    assert any("Начислен бонус" in t for t in outbox.to(2001))
    st = await referrals.stats(2001)
    assert st == {"invited": 1, "qualified": 1, "earned": 300, "paid": 0}


async def test_referral_employer_qualifies():
    async with async_session() as s:
        await make_worker(s, 2001)
        emp = await make_employer(s, uid=1000)
        s.add(Referral(referrer_id=2001, referred_id=1000, status="invited"))
        await s.commit()
        await make_order(s, emp, status=OrderStatus.SHIFT_COMPLETED)
    assert await referrals.run_referrals() == 1


# ==== Документы ====

async def test_document_upload_via_bot(dp, outbox):
    async with async_session() as s:
        await make_worker(s, 2001)
    await feed(dp, callback_update(2001, "wd:type:passport"))
    photo = [{"file_id": "small", "file_unique_id": "u1", "width": 90, "height": 90},
             {"file_id": "BIG_FILE_ID", "file_unique_id": "u2", "width": 1280, "height": 960}]
    await feed(dp, message_update(2001, photo=photo))
    async with async_session() as s:
        doc = (await s.execute(select(WorkerDocument))).scalar_one()
    assert (doc.file_id, doc.doc_type, doc.status) == ("BIG_FILE_ID", "passport", "pending")
    assert any("Новый документ" in t for t in outbox.to(999))


# ==== Города ====

async def test_cities_seed_and_cache():
    async with async_session() as s:
        names = await cities.refresh_async(s)
    assert names == ["Петрозаводск"]
    async with async_session() as s:
        s.add(City(name="Кондопога", sort_order=5))
        s.add(City(name="Сортавала", sort_order=6, is_active=False))
        await s.commit()
        assert await cities.refresh_async(s) == ["Петрозаводск", "Кондопога"]
    assert cities.is_active("Кондопога") and not cities.is_active("Сортавала")


async def test_worker_registration_and_city_change_use_city_list(dp, outbox):
    async with async_session() as s:
        s.add(City(name="Кондопога", sort_order=5))
        await s.commit()
        await cities.refresh_async(s)
        await make_worker(s, 2001)
    from bot.keyboards.inline import get_cities_keyboard
    labels = [b.text for row in get_cities_keyboard().inline_keyboard for b in row]
    assert labels == ["Петрозаводск", "Кондопога"]

    await feed(dp, callback_update(2001, "wcity:Кондопога"))
    async with async_session() as s:
        from database.models import Worker
        w = (await s.execute(select(Worker).where(Worker.user_id == 2001))).scalar_one()
    assert w.city == "Кондопога"
    await feed(dp, callback_update(2001, "wcity:Москва"))
    assert "Этот город сейчас недоступен" in outbox.answers()


async def test_order_goes_to_workers_of_its_city(outbox):
    from bot.utils import lifecycle as L
    async with async_session() as s:
        s.add(City(name="Кондопога", sort_order=5))
        await s.commit()
        emp = await make_employer(s)
        await make_worker(s, 2001, city="Петрозаводск")
        await make_worker(s, 2002, city="Кондопога")
        order = await make_order(s, emp, city="Кондопога", status=OrderStatus.CREATED)
    await L.approve_order(order.id, "admin")
    assert outbox.to(2002) and not outbox.to(2001)


# ==== Миграция ====

def test_upgrade_schema_on_old_database_keeps_data():
    """Старая база без новых колонок и таблиц: миграция только добавляет, данные целы"""
    from database.migrate import upgrade_schema
    path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id BIGINT PRIMARY KEY, username VARCHAR(255), first_name VARCHAR(255),
            last_name VARCHAR(255), phone VARCHAR(20), role VARCHAR(50), is_blocked BOOLEAN,
            created_at DATETIME, updated_at DATETIME);
        CREATE TABLE workers (id INTEGER PRIMARY KEY, user_id BIGINT NOT NULL UNIQUE, city VARCHAR(100) NOT NULL,
            categories TEXT NOT NULL, photo_url VARCHAR(500), rating FLOAT, total_reviews INTEGER,
            completed_shifts INTEGER, punctuality_rating FLOAT, responsibility_rating FLOAT, quality_rating FLOAT,
            communication_rating FLOAT, created_at DATETIME, updated_at DATETIME);
        INSERT INTO users (id, first_name, role) VALUES (1, 'Пётр', 'worker');
        INSERT INTO workers (id, user_id, city, categories, completed_shifts) VALUES (1, 1, 'Медвежьегорск', '[]', 7);
    """)
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        changes = upgrade_schema(conn)
    assert "add column workers.verified_at" in changes
    assert any(c.startswith("create table referrals") for c in changes)
    with engine.begin() as conn:
        assert upgrade_schema(conn) == []  # повторный запуск ничего не меняет
        cols = {c["name"] for c in inspect(conn).get_columns("workers")}
        assert "verified_at" in cols
        row = conn.exec_driver_sql("SELECT city, completed_shifts FROM workers").one()
        assert tuple(row) == ("Медвежьегорск", 7)
        names = [r[0] for r in conn.exec_driver_sql("SELECT name FROM cities ORDER BY sort_order")]
        assert names == ["Петрозаводск", "Медвежьегорск"]
    engine.dispose()
