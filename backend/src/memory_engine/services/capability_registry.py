"""Capability registry: runtime registration, heartbeat, parse/call binding."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError
from memory_engine.integrations import redis_cache
from memory_engine.models.schema import CapabilityRegistry
from memory_engine.schemas.capability import CapabilityOut, CapabilityRegisterBody


def _to_out(row: CapabilityRegistry) -> CapabilityOut:
    last_seen = row.last_seen_time
    if hasattr(last_seen, "isoformat"):
        last_seen = last_seen.isoformat()
    return CapabilityOut(
        id=row.id,
        tenant_id=row.tenant_id,
        org_id=row.org_id,
        capability_name=row.capability_name,
        module_name=row.module_name,
        service_name=row.service_name,
        rule_kind=row.rule_kind,
        slot_name=row.slot_name,
        config_json=row.config_json,
        enabled=row.enabled,
        last_seen_time=last_seen,
        heartbeat_version=row.heartbeat_version,
        code_fingerprint=row.code_fingerprint,
        version=row.version,
    )


async def _next_version(
    session: AsyncSession, ctx: RequestContext, capability_name: str, rule_kind: str
) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(CapabilityRegistry.version), 0)).where(
            CapabilityRegistry.tenant_id == ctx.tenant_id,
            CapabilityRegistry.org_id == ctx.org_id,
            CapabilityRegistry.capability_name == capability_name,
            CapabilityRegistry.rule_kind == rule_kind,
        )
    )
    return int(result.scalar_one()) + 1


async def get_capability(
    session: AsyncSession,
    ctx: RequestContext,
    capability_name: str,
    rule_kind: str,
) -> CapabilityOut | None:
    """Get latest active capability as API model."""
    row = await get_active(session, ctx, capability_name, rule_kind)
    return _to_out(row) if row else None


async def get_active(
    session: AsyncSession,
    ctx: RequestContext,
    capability_name: str,
    rule_kind: str,
) -> CapabilityRegistry | None:
    """Load latest active capability by name and kind."""
    cached = await redis_cache.get_capability_cache(
        ctx.tenant_id, ctx.org_id, capability_name, rule_kind
    )
    if cached and cached.get("id") and cached.get("deleted", 0) == 0:
        result = await session.execute(
            select(CapabilityRegistry).where(
                CapabilityRegistry.id == cached["id"],
                CapabilityRegistry.deleted == 0,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return row

    result = await session.execute(
        select(CapabilityRegistry)
        .where(
            CapabilityRegistry.tenant_id == ctx.tenant_id,
            CapabilityRegistry.org_id == ctx.org_id,
            CapabilityRegistry.capability_name == capability_name,
            CapabilityRegistry.rule_kind == rule_kind,
            CapabilityRegistry.deleted == 0,
        )
        .order_by(CapabilityRegistry.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def register(
    session: AsyncSession,
    ctx: RequestContext,
    body: CapabilityRegisterBody,
) -> CapabilityOut:
    """Register capability (versioned upsert: soft-delete old + insert new)."""
    current = await get_active(session, ctx, body.capability_name, body.rule_kind)
    if current and (
        current.module_name == body.module_name
        and current.service_name == body.service_name
        and current.config_json == body.config_json
        and current.enabled == body.enabled
    ):
        await heartbeat(
            session,
            ctx,
            capability_name=body.capability_name,
            rule_kind=body.rule_kind,
            code_fingerprint=body.code_fingerprint,
        )
        return _to_out(current)

    if current:
        await session.execute(
            update(CapabilityRegistry)
            .where(CapabilityRegistry.id == current.id)
            .values(deleted=1, updated_by=ctx.user_id)
        )

    version = await _next_version(session, ctx, body.capability_name, body.rule_kind)
    now_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")[:26]
    row = CapabilityRegistry(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        capability_name=body.capability_name,
        module_name=body.module_name,
        service_name=body.service_name,
        rule_kind=body.rule_kind,
        slot_name=body.slot_name,
        config_json=body.config_json,
        enabled=body.enabled,
        code_fingerprint=body.code_fingerprint,
        version=version,
        owner_user_id=ctx.user_id,
        last_seen_time=now_str,
        heartbeat_version=1,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    out = _to_out(row)
    await session.commit()
    await redis_cache.set_capability_cache(
        ctx.tenant_id,
        ctx.org_id,
        body.capability_name,
        body.rule_kind,
        out.model_dump(),
    )
    return out


async def heartbeat(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    capability_name: str,
    rule_kind: str,
    code_fingerprint: str | None = None,
) -> CapabilityOut:
    """Bump heartbeat for an existing capability."""
    row = await get_active(session, ctx, capability_name, rule_kind)
    if not row:
        raise NotFoundError(f"capability '{capability_name}' ({rule_kind}) not found")

    now_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")[:26]
    row.last_seen_time = now_str
    row.heartbeat_version = int(row.heartbeat_version) + 1
    if code_fingerprint:
        row.code_fingerprint = code_fingerprint
    row.updated_by = ctx.user_id
    await session.commit()
    out = _to_out(row)
    await redis_cache.set_capability_cache(
        ctx.tenant_id, ctx.org_id, capability_name, rule_kind, out.model_dump()
    )
    return out


async def resolve_capability_id(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    capability_id: int | None = None,
    capability_name: str | None = None,
    module_name: str | None = None,
    service_name: str | None = None,
    rule_kind: str = "parse",
    slot_name: str | None = None,
    config_json: dict | None = None,
    code_fingerprint: str | None = None,
) -> int | None:
    """Resolve or auto-register capability for parse/call rule binding."""
    if capability_id:
        return capability_id
    if not capability_name or not module_name or not service_name:
        return None

    body = CapabilityRegisterBody(
        capability_name=capability_name,
        module_name=module_name,
        service_name=service_name,
        rule_kind=rule_kind,
        slot_name=slot_name,
        config_json=config_json,
        code_fingerprint=code_fingerprint,
    )
    out = await register(session, ctx, body)
    return out.id


async def list_capabilities(
    session: AsyncSession, ctx: RequestContext, *, rule_kind: str | None = None, limit: int = 100
) -> list[CapabilityOut]:
    stmt = select(CapabilityRegistry).where(
        CapabilityRegistry.tenant_id == ctx.tenant_id,
        CapabilityRegistry.org_id == ctx.org_id,
        CapabilityRegistry.deleted == 0,
    )
    if rule_kind:
        stmt = stmt.where(CapabilityRegistry.rule_kind == rule_kind)
    result = await session.execute(stmt.order_by(CapabilityRegistry.update_time.desc()).limit(limit))
    return [_to_out(r) for r in result.scalars().all()]


async def delete_soft(
    session: AsyncSession, ctx: RequestContext, capability_name: str, rule_kind: str
) -> None:
    rows = await session.execute(
        select(CapabilityRegistry).where(
            CapabilityRegistry.tenant_id == ctx.tenant_id,
            CapabilityRegistry.org_id == ctx.org_id,
            CapabilityRegistry.capability_name == capability_name,
            CapabilityRegistry.rule_kind == rule_kind,
            CapabilityRegistry.deleted == 0,
        )
    )
    items = list(rows.scalars().all())
    if not items:
        raise NotFoundError(f"capability '{capability_name}' not found")
    for item in items:
        item.deleted = 1
        item.updated_by = ctx.user_id
    await session.commit()
    await redis_cache.delete_capability_cache(ctx.tenant_id, ctx.org_id, capability_name, rule_kind)
