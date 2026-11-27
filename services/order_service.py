"""
Сервис для работы с заказами
"""
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Order, Employer
from config import OrderStatus


class OrderService:
    """Сервис для управления заказами"""
    
    @staticmethod
    async def create_order(
        session: AsyncSession,
        employer_id: int,
        city: str,
        address: str,
        shift_date: datetime,
        shift_duration: int,
        workers_needed: int,
        category: str,
        description: str,
        payment_type: str,
        payment_amount: float,
        requirements: str = None
    ) -> Order:
        """Создать новый заказ"""
        from config import calculate_order_cost
        
        # Тот же расчёт, что показывается работодателю в боте
        cost = calculate_order_cost(
            payment_type, payment_amount, shift_duration, workers_needed
        )
        commission = cost["commission_total"]
        
        order = Order(
            employer_id=employer_id,
            city=city,
            address=address,
            shift_date=shift_date,
            shift_duration=shift_duration,
            workers_needed=workers_needed,
            category=category,
            description=description,
            requirements=requirements,
            payment_type=payment_type,
            payment_amount=payment_amount,
            commission=commission,
            prepayment_amount=cost["prepayment"],
            status=OrderStatus.CREATED
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order
    
    @staticmethod
    async def get_order(session: AsyncSession, order_id: int) -> Order:
        """Получить заказ по ID"""
        result = await session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_employer_orders(
        session: AsyncSession,
        employer_id: int,
        status: str = None
    ):
        """Получить заказы работодателя"""
        query = select(Order).where(Order.employer_id == employer_id)
        
        if status:
            query = query.where(Order.status == status)
        
        query = query.order_by(Order.created_at.desc())
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_orders_by_status(session: AsyncSession, status: str):
        """Получить заказы по статусу"""
        result = await session.execute(
            select(Order)
            .where(Order.status == status)
            .order_by(Order.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_orders_by_city_and_category(
        session: AsyncSession,
        city: str,
        category: str
    ):
        """Получить активные заказы по городу и категории"""
        result = await session.execute(
            select(Order)
            .where(
                and_(
                    Order.city == city,
                    Order.category == category,
                    Order.status == OrderStatus.SEARCH_WORKERS
                )
            )
            .order_by(Order.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_active_orders_by_city(session: AsyncSession, city: str):
        """Получить все активные заказы в городе (для работников без категорий)"""
        result = await session.execute(
            select(Order)
            .where(
                and_(
                    Order.city == city,
                    Order.status == OrderStatus.SEARCH_WORKERS
                )
            )
            .order_by(Order.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def update_status(
        session: AsyncSession,
        order_id: int,
        status: str
    ) -> bool:
        """Обновить статус заказа"""
        order = await OrderService.get_order(session, order_id)
        if order:
            order.status = status
            
            # Обновляем соответствующие даты
            if status == OrderStatus.MODERATION:
                order.moderated_at = datetime.utcnow()
            elif status == OrderStatus.SHIFT_STARTED:
                order.started_at = datetime.utcnow()
            elif status == OrderStatus.SHIFT_COMPLETED:
                order.completed_at = datetime.utcnow()
            elif status == OrderStatus.PAYMENT_COMPLETED:
                order.closed_at = datetime.utcnow()
            
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def approve_order(session: AsyncSession, order_id: int) -> bool:
        """Одобрить заказ и начать поиск работников"""
        return await OrderService.update_status(
            session, order_id, OrderStatus.SEARCH_WORKERS
        )
    
    @staticmethod
    async def reject_order(
        session: AsyncSession,
        order_id: int,
        reason: str
    ) -> bool:
        """Отклонить заказ"""
        order = await OrderService.get_order(session, order_id)
        if order:
            order.status = OrderStatus.CANCELLED
            order.rejection_reason = reason
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def cancel_order(session: AsyncSession, order_id: int) -> bool:
        """Отменить заказ"""
        return await OrderService.update_status(
            session, order_id, OrderStatus.CANCELLED
        )
