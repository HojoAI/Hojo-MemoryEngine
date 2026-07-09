"""Resolve Mongo/Qdrant partition and tenant scope for end-user APIs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.models.auth import ApiKey
from memory_engine.models.tenant import AppUser


async def resolve_end_user_tenant_org(
    session: AsyncSession,
    platform_user_id: str,
    x_tenant_id: int | None,
    x_org_id: int | None,
) -> tuple[int, int]:
    """Tenant/org from headers or linked ``app_user`` / defaults."""
    if x_tenant_id is not None:
        return x_tenant_id, x_org_id or 0

    user = await _find_app_user(session, platform_user_id)
    if user is not None:
        return user.tenant_id, user.org_id

    settings = get_settings()
    if settings.end_user_default_tenant_id is None:
        raise UserApiError("ILLEGAL_ARGUMENT", "缺少租户上下文（X-Tenant-Id 或未绑定用户）")
    return settings.end_user_default_tenant_id, settings.end_user_default_org_id


async def resolve_end_user_memory_user_id(
    session: AsyncSession,
    platform_user_id: str,
    tenant_id: int,
    org_id: int,
) -> str:
    """Map platform ``X-User-Id`` to Mongo ``memory_data.user_id`` (API key prefix when linked)."""
    user = await _find_app_user(session, platform_user_id, tenant_id=tenant_id)
    if user is not None:
        row = (
            await session.execute(
                select(ApiKey)
                .where(
                    ApiKey.user_id == user.id,
                    ApiKey.tenant_id == tenant_id,
                    ApiKey.org_id == org_id,
                    ApiKey.deleted == 0,
                    ApiKey.revoked_at.is_(None),
                )
                .order_by(ApiKey.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.key_prefix

    return platform_user_id


async def _find_app_user(
    session: AsyncSession,
    platform_user_id: str,
    tenant_id: int | None = None,
) -> AppUser | None:
    """Match MemoryEngine ``app_user`` by platform id, supabase id, or numeric PK."""
    clauses = [
        AppUser.deleted == 0,
        AppUser.status == "active",
    ]
    if tenant_id is not None:
        clauses.append(AppUser.tenant_id == tenant_id)

    if platform_user_id.isdigit():
        uid = int(platform_user_id)
        row = (
            await session.execute(select(AppUser).where(AppUser.id == uid, *clauses))
        ).scalar_one_or_none()
        if row is not None:
            return row

    row = (
        await session.execute(
            select(AppUser).where(AppUser.supabase_user_id == platform_user_id, *clauses)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    rows = (await session.execute(select(AppUser).where(*clauses).limit(200))).scalars().all()
    for candidate in rows:
        meta = candidate.metadata_json or {}
        if str(meta.get("platform_user_id", "")) == platform_user_id:
            return candidate
    return None
