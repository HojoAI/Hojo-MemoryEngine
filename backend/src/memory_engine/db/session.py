"""Database session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memory_engine.config import get_settings

_settings = get_settings()
# pool_pre_ping=False: SQLAlchemy 2.0.x + aiomysql async ping() signature mismatch (TypeError: reconnect)
engine = create_async_engine(_settings.mysql_dsn, echo=_settings.app_debug, pool_pre_ping=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a DB session."""
    async with SessionLocal() as session:
        yield session
