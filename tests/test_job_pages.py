from database import async_session
from tests.conftest import make_employer, make_worker, make_order, feed, message_update, callback_update


async def test_job_pages_use_worker_identity(dp, outbox):
    async with async_session() as s:
        employer = await make_employer(s)
        await make_worker(s, 2001)
        orders = [await make_order(s, employer, hours_ahead=24+i) for i in range(7)]
    await feed(dp, message_update(2001, "🔍 Найти работу"))
    cards = [t for t in outbox.to(2001) if "Вакансия #" in t]
    assert len(cards) == 5
    assert "jobs:page:1" in outbox.buttons_to(2001)
    outbox.clear()
    await feed(dp, callback_update(2001, "jobs:page:1"))
    cards = [t for t in outbox.to(2001) if "Вакансия #" in t]
    assert len(cards) == 2
    assert f"#{orders[5].id}</b>" in cards[0]
    assert "jobs:page:0" in outbox.buttons_to(2001)
    outbox.clear()
    await feed(dp, callback_update(2001, "jobs:page:999"))
    assert len([t for t in outbox.to(2001) if "Вакансия #" in t]) == 2
