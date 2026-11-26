"""
Сервис для работы с пользователями
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User


class UserService:
    """Сервис для управления пользователями"""
    
    @staticmethod
    async def get_user(session: AsyncSession, user_id: int) -> User:
        """Получить пользователя по ID"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_user(
        session: AsyncSession,
        user_id: int,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
        role: str = None
    ) -> User:
        """Создать нового пользователя"""
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            role=role
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    
    @staticmethod
    async def update_user(
        session: AsyncSession,
        user_id: int,
        **kwargs
    ) -> User:
        """Обновить данные пользователя"""
        user = await UserService.get_user(session, user_id)
        if user:
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            await session.commit()
            await session.refresh(user)
        return user
    
    @staticmethod
    async def block_user(session: AsyncSession, user_id: int) -> bool:
        """Заблокировать пользователя"""
        user = await UserService.get_user(session, user_id)
        if user:
            user.is_blocked = True
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def unblock_user(session: AsyncSession, user_id: int) -> bool:
        """Разблокировать пользователя"""
        user = await UserService.get_user(session, user_id)
        if user:
            user.is_blocked = False
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def is_blocked(session: AsyncSession, user_id: int) -> bool:
        """Проверить, заблокирован ли пользователь"""
        user = await UserService.get_user(session, user_id)
        return user.is_blocked if user else False
