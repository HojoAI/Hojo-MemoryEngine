"""Offline-style capability consistency scan (stale heartbeat detection)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.models.schema import CapabilityRegistry


async def scan_stale_capabilities(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    stale_hours: int = 72,
) -> list[dict]:
    """List capabilities not seen recently (for ops / dashboard)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=stale_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    result = await session.execute(
        select(CapabilityRegistry).where(
            CapabilityRegistry.tenant_id == ctx.tenant_id,
            CapabilityRegistry.org_id == ctx.org_id,
            CapabilityRegistry.deleted == 0,
            CapabilityRegistry.enabled == 1,
        )
    )
    stale: list[dict] = []
    for row in result.scalars().all():
        last = row.last_seen_time
        if last is None or str(last) < cutoff:
            stale.append(
                {
                    "id": row.id,
                    "capability_name": row.capability_name,
                    "rule_kind": row.rule_kind,
                    "module_name": row.module_name,
                    "service_name": row.service_name,
                    "last_seen_time": last,
                    "heartbeat_version": row.heartbeat_version,
                    "code_fingerprint": row.code_fingerprint,
                }
            )
    return stale
