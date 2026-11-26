"""
Автоматически одобрить всех работодателей
"""
import asyncio
from database import async_session
from services import EmployerService
from sqlalchemy import select
from database.models import Employer
from config import EmployerStatus

async def approve_all():
    async with async_session() as session:
        result = await session.execute(
            select(Employer).where(Employer.status == EmployerStatus.PENDING)
        )
        employers = result.scalars().all()
        
        if not employers:
            print("❌ Нет работодателей на проверке")
            return
        
        for employer in employers:
            await EmployerService.approve_employer(session, employer.id)
            print(f"✅ Одобрен: {employer.company_name} (ID: {employer.id}, User ID: {employer.user_id})")
        
        print(f"\n✅ Всего одобрено: {len(employers)}")

asyncio.run(approve_all())
