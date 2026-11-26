"""
Проверка статуса работодателя
"""
import asyncio
from database import async_session
from services import EmployerService, UserService

async def check():
    async with async_session() as session:
        # Получаем всех пользователей
        from sqlalchemy import select
        from database.models import User, Employer
        
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        print("=== Пользователи ===")
        for user in users:
            print(f"ID: {user.id}, Роль: {user.role}, Имя: {user.first_name} {user.last_name or ''}")
            
            if user.role == "employer":
                employer = await EmployerService.get_employer(session, user.id)
                if employer:
                    print(f"  Компания: {employer.company_name}")
                    print(f"  Статус: {employer.status}")
                    print(f"  ID работодателя: {employer.id}")
                else:
                    print(f"  РАБОТОДАТЕЛЬ НЕ НАЙДЕН!")
            print()

asyncio.run(check())
