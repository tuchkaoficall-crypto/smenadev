"""
Сервис для работы с отзывами
"""
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Review, Worker
from services.worker_service import WorkerService


class ReviewService:
    """Сервис для управления отзывами"""
    
    @staticmethod
    async def create_review(
        session: AsyncSession,
        order_id: int,
        worker_id: int,
        employer_id: int,
        rating: int,
        punctuality: int = None,
        responsibility: int = None,
        quality: int = None,
        communication: int = None,
        comment: str = None
    ) -> Review:
        """Создать отзыв о работнике"""
        # Проверяем, нет ли уже отзыва
        existing = await ReviewService.get_review_by_order_and_worker(
            session, order_id, worker_id, employer_id
        )
        
        if existing:
            return existing
        
        review = Review(
            order_id=order_id,
            worker_id=worker_id,
            employer_id=employer_id,
            rating=rating,
            punctuality=punctuality,
            responsibility=responsibility,
            quality=quality,
            communication=communication,
            comment=comment
        )
        session.add(review)
        await session.flush()
        
        # Обновляем рейтинг работника
        await WorkerService.update_rating(
            session,
            worker_id,
            rating,
            punctuality,
            responsibility,
            quality,
            communication
        )
        
        await session.commit()
        await session.refresh(review)
        return review
    
    @staticmethod
    async def get_review(session: AsyncSession, review_id: int) -> Review:
        """Получить отзыв по ID"""
        result = await session.execute(
            select(Review).where(Review.id == review_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_review_by_order_and_worker(
        session: AsyncSession,
        order_id: int,
        worker_id: int,
        employer_id: int
    ) -> Review:
        """Получить отзыв работодателя о работнике за конкретную смену"""
        result = await session.execute(
            select(Review).where(
                and_(
                    Review.order_id == order_id,
                    Review.worker_id == worker_id,
                    Review.employer_id == employer_id
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_worker_reviews(
        session: AsyncSession,
        worker_id: int,
        limit: int = None
    ):
        """Получить все отзывы о работнике"""
        query = (
            select(Review)
            .where(and_(Review.worker_id == worker_id, Review.is_hidden == False))
            .order_by(Review.created_at.desc())
        )
        
        if limit:
            query = query.limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_order_reviews(session: AsyncSession, order_id: int):
        """Получить все отзывы по заказу"""
        result = await session.execute(
            select(Review)
            .where(Review.order_id == order_id)
            .order_by(Review.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def hide_review(
        session: AsyncSession,
        review_id: int,
        reason: str
    ) -> bool:
        """Скрыть отзыв (администратор)"""
        review = await ReviewService.get_review(session, review_id)
        if review:
            review.is_hidden = True
            review.hidden_reason = reason
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def unhide_review(session: AsyncSession, review_id: int) -> bool:
        """Показать скрытый отзыв"""
        review = await ReviewService.get_review(session, review_id)
        if review:
            review.is_hidden = False
            review.hidden_reason = None
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def can_review(
        session: AsyncSession,
        order_id: int,
        worker_id: int,
        employer_id: int
    ) -> bool:
        """Проверить, может ли работодатель оставить отзыв"""
        existing = await ReviewService.get_review_by_order_and_worker(
            session, order_id, worker_id, employer_id
        )
        return existing is None
