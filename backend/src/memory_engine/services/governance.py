"""Governance and Dreaming orchestration."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError
from memory_engine.models.governance import DreamingJob, DreamingJobRun
from memory_engine.services.workflow_launch import launch_dreaming_run
from memory_engine.temporal.params import DreamingRunInput


async def get_dreaming_job(
    session: AsyncSession, ctx: RequestContext, job_id: int
) -> DreamingJob:
    """Load dreaming job scoped to tenant."""
    row = (
        await session.execute(
            select(DreamingJob).where(
                DreamingJob.id == job_id,
                DreamingJob.tenant_id == ctx.tenant_id,
                DreamingJob.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError(f"dreaming job {job_id} not found")
    return row


async def trigger_dreaming_run(
    session: AsyncSession,
    ctx: RequestContext,
    job_id: int,
    *,
    trigger_type: str = "manual",
    wait: bool = False,
) -> dict:
    """Create dreaming_job_run row and start Temporal workflow."""
    job = await get_dreaming_job(session, ctx, job_id)
    if job.status != "enabled":
        raise NotFoundError(f"dreaming job {job_id} is not enabled")

    run_uuid = str(uuid.uuid4())
    workflow_id = f"dreaming-{ctx.tenant_id}-{job_id}-{run_uuid}"
    run_row = DreamingJobRun(
        run_uuid=run_uuid,
        job_id=job.id,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        temporal_workflow_id=workflow_id,
        temporal_run_id="pending",
        trigger_type=trigger_type,
        triggered_by_user_id=ctx.user_id,
        status="queued",
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(run_row)
    await session.flush()

    payload = DreamingRunInput(
        run_uuid=run_uuid,
        job_id=job.id,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        job_name=job.job_name,
        tier=job.tier,
        engine=job.engine,
        config_json=job.config_json,
    )
    launch = await launch_dreaming_run(
        run_uuid=run_uuid,
        workflow_id=workflow_id,
        payload=payload,
        wait=wait,
    )
    run_row.temporal_run_id = launch["run_id"]
    await session.commit()
    return {
        "run_uuid": run_uuid,
        "job_id": job.id,
        "temporal_workflow_id": workflow_id,
        "temporal_run_id": launch["run_id"],
        "status": launch["status"],
        "result": launch.get("result"),
    }


async def get_dreaming_run(
    session: AsyncSession, ctx: RequestContext, run_uuid: str
) -> DreamingJobRun:
    """Load dreaming run scoped to tenant."""
    row = (
        await session.execute(
            select(DreamingJobRun).where(
                DreamingJobRun.run_uuid == run_uuid,
                DreamingJobRun.tenant_id == ctx.tenant_id,
                DreamingJobRun.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError(f"dreaming run {run_uuid} not found")
    return row
