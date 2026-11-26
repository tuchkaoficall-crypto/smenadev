"""
Проверка базы данных
"""
import asyncio
from database import async_session
from database.models import User, Worker
from sqlalchemy import select

async def check_data():
    async with async_session() as session:
        # Проверяем пользователей
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"📊 Пользователей в базе: {len(users)}")
        for user in users:
            print(f"  - User ID: {user.id}, Name: {user.full_name}, Role: {user.role}")
        
        print()
        
        # Проверяем работников
        result = await session.execute(select(Worker))
        workers = result.scalars().all()
        print(f"📊 Работников в базе: {len(workers)}")
        for worker in workers:
            print(f"  - Worker ID: {worker.id}, User ID: {worker.user_id}, City: {worker.city}")

if __name__ == "__main__":
    asyncio.run(check_data())
