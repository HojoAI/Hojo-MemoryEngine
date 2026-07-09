"""Dreaming job Temporal activities (Light / REM / Deep tiers)."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from temporalio import activity

from memory_engine.core.context import RequestContext
from memory_engine.db.session import SessionLocal
from memory_engine.models.governance import DreamingJobRun
from memory_engine.models.schema import MemoryField
from memory_engine.services import governance_apply
from memory_engine.temporal.params import DreamingRunInput


@activity.defn(name="dreaming_update_run_status")
async def dreaming_update_run_status(
    run_uuid: str,
    status: str,
    failure_reason: str | None = None,
    stats_json: dict[str, Any] | None = None,
) -> None:
    """Persist dreaming_job_run status transitions."""
    now = datetime.utcnow()
    async with SessionLocal() as session:
        result = await session.execute(
            select(DreamingJobRun).where(DreamingJobRun.run_uuid == run_uuid, DreamingJobRun.deleted == 0)
        )
        row = result.scalar_one_or_none()
        if not row:
            activity.logger.warning("dreaming run not found", extra={"run_uuid": run_uuid})
            return
        row.status = status
        if status == "running" and row.started_at is None:
            row.started_at = now
        if status in {"succeeded", "failed", "cancelled", "timed_out"}:
            row.finished_at = now
        if failure_reason:
            row.failure_reason = failure_reason[:1024]
        if stats_json is not None:
            row.stats_json = stats_json
        await session.commit()


@activity.defn(name="dreaming_execute_analytics")
async def dreaming_execute_analytics(payload: DreamingRunInput) -> dict[str, Any]:
    """Tier-based governance analytics; produces proposals for review or auto-apply."""
    ctx = RequestContext(
        tenant_id=payload.tenant_id,
        org_id=payload.org_id,
        user_id=payload.user_id,
    )
    proposals_created = 0
    records_scanned = 0

    async with SessionLocal() as session:
        if payload.tier == "LIGHT":
            limit = 20
            confidence = 0.85
            risk = "low"
        elif payload.tier == "REM":
            limit = 100
            confidence = 0.75
            risk = "medium"
        else:
            limit = 500
            confidence = 0.65
            risk = "medium"

        dupes = await session.execute(
            select(MemoryField.name, func.count(MemoryField.id).label("cnt"))
            .where(
                MemoryField.tenant_id == ctx.tenant_id,
                MemoryField.org_id == ctx.org_id,
                MemoryField.deleted == 0,
            )
            .group_by(MemoryField.name)
            .having(func.count(MemoryField.id) > 1)
            .limit(limit)
        )
        for name, cnt in dupes.all():
            records_scanned += int(cnt)
            await governance_apply.create_proposal_from_dreaming(
                session,
                ctx,
                job_run_id=None,
                target_type="memory_field",
                action="update",
                target_ref_json={"name": name},
                payload_json={
                    "description": f"Dreaming {payload.tier}: consolidate duplicate schema versions"
                },
                confidence_score=confidence,
                risk_level=risk,
                evidence_json={"duplicate_rows": int(cnt), "tier": payload.tier},
            )
            proposals_created += 1

        inactive = await session.execute(
            select(MemoryField)
            .where(
                MemoryField.tenant_id == ctx.tenant_id,
                MemoryField.org_id == ctx.org_id,
                MemoryField.deleted == 0,
                MemoryField.status == "deprecated",
            )
            .limit(limit)
        )
        for mf in inactive.scalars().all():
            records_scanned += 1
            await governance_apply.create_proposal_from_dreaming(
                session,
                ctx,
                job_run_id=None,
                target_type="memory_field",
                action="delete",
                target_ref_json={"name": mf.name},
                payload_json={},
                confidence_score=0.95,
                risk_level="low",
                evidence_json={"reason": "deprecated_status", "tier": payload.tier},
            )
            proposals_created += 1

    return {
        "engine": payload.engine,
        "tier": payload.tier,
        "proposals_suggested": proposals_created,
        "records_scanned": records_scanned,
    }


@activity.defn(name="dreaming_finalize_run")
async def dreaming_finalize_run(run_uuid: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Mark run succeeded with stats."""
    await dreaming_update_run_status(run_uuid, "succeeded", stats_json=stats)
    return stats
