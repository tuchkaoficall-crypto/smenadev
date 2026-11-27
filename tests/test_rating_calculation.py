"""Rating regressions: optional criteria, moderation and transaction boundaries."""
import pytest
from database import async_session
from database.models import Review
from services.review_service import ReviewService
from tests.conftest import make_employer, make_worker, make_order


async def test_optional_criteria_moderation_and_duplicate():
    async with async_session() as s:
        emp = await make_employer(s)
        worker = await make_worker(s, 2001)
        first_order = await make_order(s, emp)
        second_order = await make_order(s, emp)
        first = await ReviewService.create_review(s, first_order.id, worker.id, emp.id, 3)
        second = await ReviewService.create_review(
            s, second_order.id, worker.id, emp.id, 5,
            punctuality=5, quality=4, responsibility=3, communication=2)
        assert worker.total_reviews == 2
        assert worker.rating == 4
        assert worker.punctuality_rating == 5
        assert worker.quality_rating == 4
        assert worker.responsibility_rating == 3
        assert worker.communication_rating == 2
        duplicate = await ReviewService.create_review(s, second_order.id, worker.id, emp.id, 1)
        assert duplicate.id == second.id
        assert worker.total_reviews == 2 and worker.rating == 4

        await ReviewService.hide_review(s, second.id, "test")
        assert worker.total_reviews == 1 and worker.rating == 3
        assert worker.punctuality_rating == 0
        await ReviewService.unhide_review(s, second.id)
        assert worker.total_reviews == 2 and worker.rating == 4
        assert worker.punctuality_rating == 5

        # The web panel uses exactly the same calculation.
        from admin import app, db_session, services
        from database.models import Worker
        with app.app_context():
            web_worker = db_session.get(Worker, worker.id)
            services.recalc_worker_rating(web_worker)
            assert web_worker.rating == worker.rating
            assert web_worker.punctuality_rating == worker.punctuality_rating

        await ReviewService.hide_review(s, first.id, "test")
        await ReviewService.hide_review(s, second.id, "test")
        assert worker.total_reviews == 0 and worker.rating == 0
        assert worker.communication_rating == 0


async def test_failed_rating_update_does_not_commit_review(monkeypatch):
    from services.worker_service import WorkerService
    async with async_session() as s:
        emp = await make_employer(s)
        worker = await make_worker(s, 2001)
        order = await make_order(s, emp)

        async def fail(*args):
            raise RuntimeError("rating unavailable")

        monkeypatch.setattr(WorkerService, "recalculate_rating", fail)
        with pytest.raises(RuntimeError, match="rating unavailable"):
            await ReviewService.create_review(s, order.id, worker.id, emp.id, 5)
        await s.rollback()
    from sqlalchemy import select
    async with async_session() as s:
        assert (await s.execute(select(Review))).scalars().all() == []
