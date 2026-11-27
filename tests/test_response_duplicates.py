import asyncio

from sqlalchemy import select
from database import async_session
from database.models import Response
from services.response_service import ResponseService
from tests.conftest import make_employer, make_worker, make_order


async def test_concurrent_requests_create_one_response():
    async with async_session() as session:
        employer = await make_employer(session)
        worker = await make_worker(session, 2001)
        order = await make_order(session, employer)
        order_id, worker_id = order.id, worker.id

    async def submit():
        async with async_session() as session:
            return await ResponseService.create_response_once(session, order_id, worker_id)

    results = await asyncio.gather(*(submit() for _ in range(5)))
    assert sum(created for _, created in results) == 1
    assert len({response.id for response, _ in results}) == 1
    async with async_session() as session:
        assert len((await session.execute(select(Response))).scalars().all()) == 1
        response = await ResponseService.create_response(session, order_id, worker_id)
        assert response.id == results[0][0].id
