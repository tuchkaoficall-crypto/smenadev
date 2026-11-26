"""
Конфигурация базы данных
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config import DATABASE_URL, USE_SQLITE

# Создание движка базы данных
if USE_SQLITE:
    # SQLite не поддерживает pool_size и max_overflow
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
    )
else:
    # PostgreSQL с pool настройками
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=20,
        max_overflow=0,
    )

# Фабрика сессий
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Базовый класс для моделей
Base = declarative_base()


async def get_session() -> AsyncSession:
    """Получение сессии базы данных"""
    async with async_session() as session:
        yield session


async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
