"""Database session factory."""

from collections.abc import AsyncGenerator

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memory_engine.config import get_settings

_settings = get_settings()
logger = logging.getLogger(__name__)
# pool_pre_ping=False: SQLAlchemy 2.0.x + aiomysql async ping() signature mismatch (TypeError: reconnect)
engine = create_async_engine(
    _settings.mysql_dsn,
    echo=_settings.app_debug,
    pool_pre_ping=False,
    pool_size=_settings.mysql_pool_size,
    max_overflow=_settings.mysql_max_overflow,
    pool_timeout=_settings.mysql_pool_timeout_seconds,
)
logger.info(
    "MySQL SQLAlchemy pool config: pool_size=%s max_overflow=%s pool_timeout_s=%s",
    _settings.mysql_pool_size,
    _settings.mysql_max_overflow,
    _settings.mysql_pool_timeout_seconds,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a DB session."""
    async with SessionLocal() as session:
        yield session


async def release_db_connection(session: AsyncSession) -> None:
    """Release any checked-out connection for read-only work.

    SQLAlchemy sessions keep the current transaction/connection after the first
    query. Rolling back a read-only transaction lets long LLM/Mongo/Qdrant work
    happen without occupying a MySQL pool slot for the full request lifetime.
    """
    if session.in_transaction():
        await session.rollback()
