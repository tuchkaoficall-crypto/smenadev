"""
Реферальная программа.

  • У каждого пользователя есть ссылка https://t.me/<бот>?start=ref_<telegram_id>.
  • Новый пользователь, пришедший по ссылке, записывается в таблицу referrals (status=invited).
  • Бонус REFERRAL_BONUS начисляется (status=qualified), когда приглашённый работник
    отработал первую смену или у приглашённого работодателя завершилась первая смена.
    Проверку делает планировщик раз в минуту, поэтому неважно, где завершили смену:
    в боте или в веб-панели.
  • Выплату бонуса отмечает администратор в веб-панели (status=paid).
"""
import logging
from datetime import datetime

from sqlalchemy import select, func

from config import REFERRAL_BONUS, OrderStatus
from database import async_session
from database.models import Referral, User, Worker, Employer, Order

logger = logging.getLogger(__name__)

PREFIX = "ref_"
_bot_username = None


def parse_payload(text: str):
    """'/start ref_123' -> 123"""
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].startswith(PREFIX):
        return None
    raw = parts[1][len(PREFIX):]
    return int(raw) if raw.isdigit() else None


async def bot_username() -> str:
    global _bot_username
    if not _bot_username:
        from bot.bot_instance import bot
        me = await bot.me()
        _bot_username = me.username
    return _bot_username


async def invite_link(user_id: int) -> str:
    return f"https://t.me/{await bot_username()}?start={PREFIX}{user_id}"


async def register_invite(referred_id: int, referrer_id: int) -> bool:
    """Записать приглашение. Только для новых пользователей и не самого себя"""
    if not referrer_id or referrer_id == referred_id:
        return False
    async with async_session() as session:
        if await session.get(User, referred_id):
            return False  # уже пользовался ботом
        if not await session.get(User, referrer_id):
            return False
        exists = (await session.execute(select(Referral.id).where(Referral.referred_id == referred_id))).first()
        if exists:
            return False
        session.add(Referral(referrer_id=referrer_id, referred_id=referred_id, status="invited"))
        await session.commit()
    from bot.utils.lifecycle import send
    await send(referrer_id, "🎁 По вашей ссылке пришёл новый пользователь! Бонус начислим, "
                            "когда он выполнит первую смену (или завершит первый заказ).")
    return True


async def stats(user_id: int) -> dict:
    async with async_session() as session:
        rows = list((await session.execute(select(Referral).where(Referral.referrer_id == user_id))).scalars().all())
    return {
        "invited": len(rows),
        "qualified": sum(1 for r in rows if r.status in ("qualified", "paid")),
        "earned": sum(r.bonus_amount or 0 for r in rows if r.status in ("qualified", "paid")),
        "paid": sum(r.bonus_amount or 0 for r in rows if r.status == "paid"),
    }


async def run_referrals() -> int:
    """Начислить бонусы за приглашённых, которые стали активными. Возвращает число начислений"""
    from bot.utils.lifecycle import send
    notified = []
    async with async_session() as session:
        pending = list((await session.execute(
            select(Referral).where(Referral.status == "invited"))).scalars().all())
        if not pending:
            return 0
        for ref in pending:
            role = None
            worker = (await session.execute(select(Worker).where(Worker.user_id == ref.referred_id))).scalar_one_or_none()
            if worker and (worker.completed_shifts or 0) >= 1:
                role = "worker"
            else:
                employer = (await session.execute(
                    select(Employer).where(Employer.user_id == ref.referred_id))).scalar_one_or_none()
                if employer:
                    done = (await session.execute(select(func.count(Order.id)).where(
                        Order.employer_id == employer.id,
                        Order.status.in_((OrderStatus.SHIFT_COMPLETED, OrderStatus.PAYMENT_COMPLETED)),
                    ))).scalar_one()
                    if done:
                        role = "employer"
            if not role:
                continue
            ref.status = "qualified"
            ref.role = role
            ref.bonus_amount = REFERRAL_BONUS
            ref.qualified_at = datetime.utcnow()
            notified.append(ref.referrer_id)
        await session.commit()

    for chat in notified:
        await send(chat, f"🎉 Ваш друг выполнил первую смену! Начислен бонус <b>{REFERRAL_BONUS:.0f} ₽</b>.\n"
                         "Администратор свяжется с вами для выплаты. Статистика: «🎁 Пригласить друга».")
    return len(notified)
