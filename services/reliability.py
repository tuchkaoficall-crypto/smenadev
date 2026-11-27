"""
Надёжность работников: штрафные баллы, уровни, приоритет в рассылке вакансий.

Правила (значения в config/settings.py):
  • отказ от подтверждённой смены < 24 ч до начала: +2 балла, < 3 ч: +3;
  • неявка (отмечает админ): +5;  отметка «на месте» с опозданием: +1;
  • баллы учитываются за последние PENALTY_WINDOW_DAYS дней (по умолчанию 90);
  • от PENALTY_RESTRICT_POINTS баллов (10) работник не получает вакансии и не может откликаться;
  • приоритет: проверенные документы или высокий рейтинг/опыт и 0 баллов — такие
    работники получают вакансию первыми, остальные через PRIORITY_DELAY_MINUTES.

Функции без БД — чистые; запросы собраны через select(), поэтому одинаково
работают и в боте (AsyncSession, await session.execute), и в админке (Session).
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select, func

from config import (
    PENALTY_POINTS, PENALTY_WINDOW_DAYS, PENALTY_RESTRICT_POINTS,
)

# ==== Чистая логика ====


def penalty_for_withdraw(hours_left: float):
    """Штраф за отказ от подтверждённой смены: (kind, points) или None"""
    if hours_left < 3:
        return "very_late_cancel", PENALTY_POINTS["very_late_cancel"]
    if hours_left < 24:
        return "late_cancel", PENALTY_POINTS["late_cancel"]
    return None


def level(points: int) -> dict:
    """Уровень надёжности по активным баллам"""
    if points >= PENALTY_RESTRICT_POINTS:
        return {"code": "restricted", "label": "Ограничен", "emoji": "⛔️", "color": "dark"}
    if points >= 5:
        return {"code": "low", "label": "Низкая надёжность", "emoji": "🔴", "color": "danger"}
    if points >= 1:
        return {"code": "warn", "label": "Есть замечания", "emoji": "🟡", "color": "warning"}
    return {"code": "good", "label": "Надёжный", "emoji": "🟢", "color": "success"}


def is_restricted(points: int) -> bool:
    return points >= PENALTY_RESTRICT_POINTS


def is_priority(worker, points: int) -> bool:
    """Первым получает вакансии: 0 баллов и (документы проверены или хороший рейтинг/опыт)"""
    if points > 0:
        return False
    if getattr(worker, "verified_at", None):
        return True
    rating = worker.rating or 0
    if (worker.total_reviews or 0) >= 1 and rating >= 4.5:
        return True
    return (worker.completed_shifts or 0) >= 5 and (not worker.total_reviews or rating >= 4.0)


def rank_key(worker, points: int):
    """Сортировка получателей: меньше штрафов, затем проверенные, затем рейтинг и опыт"""
    return (
        points,
        0 if getattr(worker, "verified_at", None) else 1,
        -(worker.rating or 0),
        -(worker.completed_shifts or 0),
    )


def worker_categories(worker) -> list:
    try:
        return json.loads(worker.categories) if worker.categories else []
    except (ValueError, TypeError):
        return []


def matches_order(worker, order) -> bool:
    """Город и категория совпадают, пользователь не заблокирован"""
    if worker.city != order.city:
        return False
    if worker.user and worker.user.is_blocked:
        return False
    cats = worker_categories(worker)
    return not cats or order.category in cats


def split_recipients(workers, points: dict):
    """Разделить подходящих работников на (приоритетные, остальные, ограниченные), с сортировкой"""
    priority, rest, restricted = [], [], []
    for w in workers:
        p = points.get(w.id, 0)
        if is_restricted(p):
            restricted.append(w)
        elif is_priority(w, p):
            priority.append(w)
        else:
            rest.append(w)
    key = lambda w: rank_key(w, points.get(w.id, 0))  # noqa: E731
    return sorted(priority, key=key), sorted(rest, key=key), restricted


# ==== Запросы ====


def window_start(now: datetime = None) -> datetime:
    return (now or datetime.utcnow()) - timedelta(days=PENALTY_WINDOW_DAYS)


def points_query(worker_ids=None, now: datetime = None):
    from database.models import WorkerPenalty
    q = select(WorkerPenalty.worker_id, func.coalesce(func.sum(WorkerPenalty.points), 0)).where(
        WorkerPenalty.is_cancelled.is_(False),
        WorkerPenalty.created_at >= window_start(now),
    ).group_by(WorkerPenalty.worker_id)
    if worker_ids is not None:
        q = q.where(WorkerPenalty.worker_id.in_(list(worker_ids)))
    return q


async def points_map_async(session, worker_ids=None) -> dict:
    return {wid: int(p) for wid, p in (await session.execute(points_query(worker_ids))).all()}


def points_map_sync(session, worker_ids=None) -> dict:
    return {wid: int(p) for wid, p in session.execute(points_query(worker_ids)).all()}


async def worker_points_async(session, worker_id: int) -> int:
    return (await points_map_async(session, [worker_id])).get(worker_id, 0)


def worker_points_sync(session, worker_id: int) -> int:
    return points_map_sync(session, [worker_id]).get(worker_id, 0)


def new_penalty(worker_id: int, kind: str, *, order_id=None, points=None, reason=None, actor=None):
    from database.models import WorkerPenalty
    return WorkerPenalty(
        worker_id=worker_id, order_id=order_id, kind=kind,
        points=PENALTY_POINTS.get(kind, 1) if points is None else points,
        reason=reason, created_by=actor,
    )


def penalty_text(kind: str, points: int, total: int, order_id=None) -> str:
    """Уведомление работнику о начислении баллов"""
    from config import PENALTY_NAMES
    lvl = level(total)
    text = (
        f"⚠️ <b>Начислены штрафные баллы: +{points}</b>\n"
        f"Причина: {PENALTY_NAMES.get(kind, kind)}"
        + (f" (смена #{order_id})" if order_id else "")
        + f"\n\nСейчас у вас {total} б. · {lvl['emoji']} {lvl['label']}.\n"
        f"Баллы сгорают через {PENALTY_WINDOW_DAYS} дней. "
    )
    if is_restricted(total):
        text += "Пока баллов много, новые вакансии не приходят. Если это ошибка, напишите администратору."
    else:
        text += (f"При {PENALTY_RESTRICT_POINTS} баллах вакансии перестанут приходить, "
                 "а надёжные работники получают их первыми.")
    return text
