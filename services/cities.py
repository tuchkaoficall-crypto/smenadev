"""
Список городов сервиса.

Хранится в таблице cities и редактируется в админ-панели. Бот держит копию
активных городов в памяти (обновляется при запуске и раз в минуту планировщиком),
чтобы клавиатуры строились без запроса к БД. Если таблица пуста или ещё не
прочитана, используется config.AVAILABLE_CITIES.
"""
from sqlalchemy import select

from config import AVAILABLE_CITIES

_cache: list = []


def active_cities() -> list:
    """Активные города в порядке сортировки (синхронно, из кэша)"""
    return list(_cache) if _cache else list(AVAILABLE_CITIES)


def set_cache(names) -> None:
    global _cache
    _cache = [n for n in names if n]


def _query(active_only=True):
    from database.models import City
    q = select(City.name).order_by(City.sort_order, City.name)
    if active_only:
        q = q.where(City.is_active.is_(True))
    return q


async def refresh_async(session) -> list:
    names = list((await session.execute(_query())).scalars().all())
    set_cache(names)
    return active_cities()


def list_sync(session, active_only=True) -> list:
    names = list(session.execute(_query(active_only)).scalars().all())
    return names or list(AVAILABLE_CITIES)


def is_active(name: str) -> bool:
    return name in active_cities()
