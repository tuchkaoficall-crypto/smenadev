"""
Сервис для работы с откликами
"""
import asyncio
from weakref import WeakValueDictionary
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Response, Order, Worker
from config import ResponseStatus


_response_locks = WeakValueDictionary()


class ResponseService:
    """Сервис для управления откликами"""
    
    @staticmethod
    async def create_response(
        session: AsyncSession,
        order_id: int,
        worker_id: int
    ) -> Response:
        """Создать отклик, вернув существующий при повторном запросе."""
        response, _ = await ResponseService.create_response_once(session, order_id, worker_id)
        return response

    @staticmethod
    async def create_response_once(session, order_id, worker_id):
        """Serialize duplicate requests within this bot process.

        Multiple processes still require a database uniqueness constraint.
        """
        key = (order_id, worker_id)
        lock = _response_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _response_locks[key] = lock
        async with lock:
            existing = await ResponseService.get_response_by_worker_and_order(
                session, worker_id, order_id)
            if existing:
                return existing, False
            response = Response(order_id=order_id, worker_id=worker_id,
                                status=ResponseStatus.PENDING)
            session.add(response)
            await session.commit()
            await session.refresh(response)
            return response, True

    @staticmethod
    async def get_response(session: AsyncSession, response_id: int) -> Response:
        """Получить отклик по ID"""
        result = await session.execute(
            select(Response).where(Response.id == response_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_response_by_worker_and_order(
        session: AsyncSession,
        worker_id: int,
        order_id: int
    ) -> Response:
        """Получить отклик работника на конкретный заказ"""
        result = await session.execute(
            select(Response).where(
                and_(
                    Response.worker_id == worker_id,
                    Response.order_id == order_id
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_order_responses(
        session: AsyncSession,
        order_id: int,
        status: str = None
    ):
        """Получить все отклики на заказ"""
        query = select(Response).where(Response.order_id == order_id)
        
        if status:
            query = query.where(Response.status == status)
        
        query = query.order_by(Response.created_at.desc())
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_worker_responses(
        session: AsyncSession,
        worker_id: int,
        status: str = None
    ):
        """Получить все отклики работника"""
        query = select(Response).where(Response.worker_id == worker_id)
        
        if status:
            query = query.where(Response.status == status)
        
        query = query.order_by(Response.created_at.desc())
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def update_status(
        session: AsyncSession,
        response_id: int,
        status: str,
        admin_comment: str = None
    ) -> bool:
        """Обновить статус отклика"""
        response = await ResponseService.get_response(session, response_id)
        if response:
            response.status = status
            
            if admin_comment:
                response.admin_comment = admin_comment
            
            # Обновляем соответствующие даты
            if status == ResponseStatus.CONTACTED:
                response.contacted_at = datetime.utcnow()
            elif status == ResponseStatus.CONFIRMED:
                response.confirmed_at = datetime.utcnow()
            elif status == ResponseStatus.COMPLETED:
                response.completed_at = datetime.utcnow()
            
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def confirm_response(session: AsyncSession, response_id: int) -> bool:
        """Подтвердить отклик"""
        return await ResponseService.update_status(
            session, response_id, ResponseStatus.CONFIRMED
        )
    
    @staticmethod
    async def reject_response(
        session: AsyncSession,
        response_id: int,
        reason: str = None
    ) -> bool:
        """Отклонить отклик"""
        return await ResponseService.update_status(
            session, response_id, ResponseStatus.REJECTED, reason
        )
    
    @staticmethod
    async def get_confirmed_count(session: AsyncSession, order_id: int) -> int:
        """Получить количество подтвержденных откликов"""
        result = await session.execute(
            select(Response).where(
                and_(
                    Response.order_id == order_id,
                    Response.status == ResponseStatus.CONFIRMED
                )
            )
        )
        return len(result.scalars().all())
    
    @staticmethod
    async def has_responded(
        session: AsyncSession,
        worker_id: int,
        order_id: int
    ) -> bool:
        """Проверить, откликнулся ли работник на заказ"""
        response = await ResponseService.get_response_by_worker_and_order(
            session, worker_id, order_id
        )
        return response is not None
