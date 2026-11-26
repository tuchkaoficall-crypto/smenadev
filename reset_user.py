"""
Сброс данных пользователя для повторной регистрации
"""
import asyncio
from database import async_session
from database.models import User, Worker
from sqlalchemy import select, delete

async def reset_user(user_id: int):
    """Удалить данные пользователя"""
    async with async_session() as session:
        # Удаляем работника
        await session.execute(delete(Worker).where(Worker.user_id == user_id))
        # Удаляем пользователя
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()
        print(f"✅ Данные пользователя {user_id} удалены!")
        print("Теперь можете пройти регистрацию заново в боте")

if __name__ == "__main__":
    # УКАЖИТЕ СЮДА ВАШ TELEGRAM ID
    YOUR_USER_ID = 6630976350  # Замените на ваш ID если другой
    
    asyncio.run(reset_user(YOUR_USER_ID))
