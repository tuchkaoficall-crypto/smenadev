"""
Сервис для работы с работниками
"""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Worker, User


class WorkerService:
    """Сервис для управления работниками"""
    
    @staticmethod
    async def get_worker(session: AsyncSession, user_id: int) -> Worker:
        """Получить профиль работника по user_id"""
        result = await session.execute(
            select(Worker).where(Worker.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_worker_by_id(session: AsyncSession, worker_id: int) -> Worker:
        """Получить работника по ID"""
        result = await session.execute(
            select(Worker).where(Worker.id == worker_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_worker(
        session: AsyncSession,
        user_id: int,
        city: str,
        categories: list
    ) -> Worker:
        """Создать профиль работника (или обновить, если он уже есть)"""
        existing = await WorkerService.get_worker(session, user_id)
        if existing:
            existing.city = city
            existing.categories = json.dumps(categories, ensure_ascii=False)
            await session.commit()
            await session.refresh(existing)
            return existing
        
        worker = Worker(
            user_id=user_id,
            city=city,
            categories=json.dumps(categories, ensure_ascii=False)
        )
        session.add(worker)
        await session.commit()
        await session.refresh(worker)
        return worker
    
    @staticmethod
    async def update_categories(
        session: AsyncSession,
        user_id: int,
        categories: list
    ) -> bool:
        """Обновить категории работника"""
        worker = await WorkerService.get_worker(session, user_id)
        if worker:
            worker.categories = json.dumps(categories, ensure_ascii=False)
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def recalculate_rating(session: AsyncSession, worker_id: int) -> bool:
        """Recalculate from persisted reviews within the caller's transaction."""
        from database.models import Review
        from services.ratings import apply_review_ratings
        worker = await WorkerService.get_worker_by_id(session, worker_id)
        if worker is None:
            return False
        reviews = (await session.execute(
            select(Review).where(Review.worker_id == worker_id, Review.is_hidden.is_(False))
        )).scalars().all()
        apply_review_ratings(worker, reviews)
        return True

    @staticmethod
    async def increment_completed_shifts(session: AsyncSession, worker_id: int) -> bool:
        """Увеличить счетчик завершенных смен"""
        worker = await WorkerService.get_worker_by_id(session, worker_id)
        if worker:
            worker.completed_shifts += 1
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def get_categories(worker: Worker) -> list:
        """Получить список категорий работника"""
        if worker and worker.categories:
            return json.loads(worker.categories)
        return []
    
    @staticmethod
    async def search_workers_by_city_and_category(
        session: AsyncSession,
        city: str,
        category: str
    ):
        """Найти работников по городу и категории"""
        result = await session.execute(
            select(Worker).where(Worker.city == city)
        )
        workers = result.scalars().all()
        
        # Фильтруем по категории.
        # Пустой список категорий означает «Любая работа» — такие работники
        # получают все вакансии своего города.
        filtered = []
        for worker in workers:
            try:
                categories = json.loads(worker.categories) if worker.categories else []
            except (ValueError, TypeError):
                categories = []
            if not categories or category in categories:
                filtered.append(worker)
        
        return filtered
