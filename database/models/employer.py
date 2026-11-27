"""
Модель работодателя
"""
from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database.database import Base


class Employer(Base):
    """
    Профиль работодателя
    """
    __tablename__ = "employers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Информация о компании
    company_name = Column(String(255), nullable=False)
    company_description = Column(Text, nullable=True)
    inn = Column(String(12), nullable=True)
    contact_person = Column(String(255), nullable=False)
    contact_phone = Column(String(20), nullable=False)
    contact_email = Column(String(255), nullable=True)
    
    # Статус проверки
    status = Column(String(50), default="pending")  # pending, approved, rejected, blocked
    rejection_reason = Column(Text, nullable=True)
    
    # Даты
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", backref="employer_profile", foreign_keys=[user_id], lazy="selectin")
    
    def __repr__(self):
        return f"<Employer {self.company_name} ({self.status})>"
