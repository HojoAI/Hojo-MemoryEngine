"""Resolve Mongo memory partition id (``user_id``) from API key context."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.models.auth import ApiKey


async def resolve_memory_user_id(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str | None,
) -> str:
    """Return explicit ``user_id`` or the current API key's ``key_prefix``."""
    if user_id:
        return user_id
    if ctx.api_key_id is None:
        raise ForbiddenError("user_id is required when API key auth is disabled")
    row = (
        await session.execute(
            select(ApiKey).where(ApiKey.id == ctx.api_key_id, ApiKey.deleted == 0)
        )
    ).scalar_one_or_none()
    if not row:
        raise ForbiddenError("API key not found")
    return row.key_prefix
