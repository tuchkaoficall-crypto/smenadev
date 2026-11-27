"""
Аддитивное обновление схемы БД без Alembic.

Что делает (только добавляет, ничего не удаляет и не меняет):
  1) создаёт недостающие таблицы (create_all c checkfirst);
  2) добавляет недостающие nullable-колонки в существующие таблицы
     (ALTER TABLE ... ADD COLUMN), например orders.latitude, workers.verified_at;
  3) заполняет справочник городов, если он пустой: города из config.AVAILABLE_CITIES
     плюс города, которые уже встречаются у работников и заказов.

Работает с синхронным соединением, поэтому вызывается и из бота
(через conn.run_sync), и из админ-панели.
"""
import logging

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def upgrade_schema(conn) -> list:
    """Обновить схему. Возвращает список выполненных изменений (для логов и тестов)"""
    from database.database import Base
    import database.models  # noqa: F401  регистрируем все модели

    changes = []
    insp = inspect(conn)
    existing = set(insp.get_table_names())
    Base.metadata.create_all(conn, checkfirst=True)
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            changes.append(f"create table {table.name}")
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            if not col.nullable and col.default is None and col.server_default is None:
                logger.warning("Колонку %s.%s нельзя добавить автоматически (NOT NULL без значения)",
                               table.name, col.name)
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'))
            changes.append(f"add column {table.name}.{col.name}")

    _seed_cities(conn, changes)
    for c in changes:
        logger.info("Миграция БД: %s", c)
    return changes


def _seed_cities(conn, changes):
    from config import AVAILABLE_CITIES
    count = conn.execute(text("SELECT COUNT(*) FROM cities")).scalar()
    if count:
        return
    names = list(AVAILABLE_CITIES)
    for table in ("workers", "orders"):
        for (name,) in conn.execute(text(f"SELECT DISTINCT city FROM {table} WHERE city IS NOT NULL")):
            name = (name or "").strip()
            if name and name not in names:
                names.append(name)
    for i, name in enumerate(names):
        conn.execute(text("INSERT INTO cities (name, is_active, sort_order, created_at) "
                          "VALUES (:n, :a, :s, CURRENT_TIMESTAMP)"), {"n": name, "a": True, "s": i})
    if names:
        changes.append(f"seed cities: {', '.join(names)}")
