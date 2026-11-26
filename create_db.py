"""
Создание базы данных напрямую
"""
import asyncio
from database.database import Base, engine

async def create_tables():
    """Создать все таблицы"""
    async with engine.begin() as conn:
        # Удаляем все таблицы
        await conn.run_sync(Base.metadata.drop_all)
        # Создаем заново
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных создана успешно!")
    print("✅ Все таблицы созданы")

if __name__ == "__main__":
    # Импортируем все модели
    from database import models
    asyncio.run(create_tables())
