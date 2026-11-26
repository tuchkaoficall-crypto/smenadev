"""
Сервис для работы с работодателями
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Employer, User
from config import EmployerStatus


class EmployerService:
    """Сервис для управления работодателями"""
    
    @staticmethod
    async def get_employer(session: AsyncSession, user_id: int) -> Employer:
        """Получить профиль работодателя по user_id"""
        result = await session.execute(
            select(Employer).where(Employer.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_employer_by_id(session: AsyncSession, employer_id: int) -> Employer:
        """Получить работодателя по ID"""
        result = await session.execute(
            select(Employer).where(Employer.id == employer_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_employer(
        session: AsyncSession,
        user_id: int,
        company_name: str,
        contact_person: str,
        contact_phone: str,
        company_description: str = None,
        inn: str = None,
        contact_email: str = None
    ) -> Employer:
        """Создать профиль работодателя"""
        employer = Employer(
            user_id=user_id,
            company_name=company_name,
            contact_person=contact_person,
            contact_phone=contact_phone,
            company_description=company_description,
            inn=inn,
            contact_email=contact_email,
            status=EmployerStatus.PENDING
        )
        session.add(employer)
        await session.commit()
        await session.refresh(employer)
        return employer
    
    @staticmethod
    async def approve_employer(session: AsyncSession, employer_id: int) -> bool:
        """Одобрить работодателя"""
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        if employer:
            employer.status = EmployerStatus.APPROVED
            employer.approved_at = datetime.utcnow()
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def reject_employer(
        session: AsyncSession,
        employer_id: int,
        reason: str
    ) -> bool:
        """Отклонить работодателя"""
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        if employer:
            employer.status = EmployerStatus.REJECTED
            employer.rejection_reason = reason
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def block_employer(session: AsyncSession, employer_id: int) -> bool:
        """Заблокировать работодателя"""
        employer = await EmployerService.get_employer_by_id(session, employer_id)
        if employer:
            employer.status = EmployerStatus.BLOCKED
            await session.commit()
            return True
        return False
    
    @staticmethod
    async def get_pending_employers(session: AsyncSession):
        """Получить список работодателей на проверке"""
        result = await session.execute(
            select(Employer)
            .where(Employer.status == EmployerStatus.PENDING)
            .order_by(Employer.created_at.desc())
        )
        return result.scalars().all()
    
    @staticmethod
    async def is_approved(session: AsyncSession, user_id: int) -> bool:
        """Проверить, одобрен ли работодатель"""
        employer = await EmployerService.get_employer(session, user_id)
        return employer and employer.status == EmployerStatus.APPROVED
