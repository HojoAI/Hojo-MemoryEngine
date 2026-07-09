"""Governance & Dreaming API routes."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import get_request_context, require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.models.governance import DreamingJob, GovernanceProposal
from memory_engine.schemas.common import ApiResponse
from memory_engine.services import governance as gov_service
from memory_engine.services import governance_apply

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/proposals", response_model=ApiResponse)
async def list_proposals(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:read")),
) -> ApiResponse:
    stmt = select(GovernanceProposal).where(
        GovernanceProposal.tenant_id == ctx.tenant_id,
        GovernanceProposal.deleted == 0,
    )
    if status:
        stmt = stmt.where(GovernanceProposal.status == status)
    stmt = stmt.order_by(GovernanceProposal.create_time.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return ApiResponse(
        data=[
            {
                "proposal_uuid": r.proposal_uuid,
                "status": r.status,
                "confidence_score": float(r.confidence_score),
                "risk_level": r.risk_level,
                "target_type": r.target_type,
                "action": r.action,
            }
            for r in rows
        ]
    )


@router.post("/proposals/{proposal_uuid}/approve", response_model=ApiResponse)
async def approve_proposal(
    proposal_uuid: str,
    decision: str = "approved",
    comment: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    row = await governance_apply.approve_proposal(
        session, ctx, proposal_uuid, decision=decision, comment=comment
    )
    return ApiResponse(data={"proposal_uuid": row.proposal_uuid, "status": row.status})


@router.post("/proposals/{proposal_uuid}/apply", response_model=ApiResponse)
async def apply_proposal(
    proposal_uuid: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    return ApiResponse(data=await governance_apply.apply_proposal(session, ctx, proposal_uuid))


@router.post("/locks", response_model=ApiResponse)
async def create_lock(
    lock_type: str,
    target_type: str,
    target_ref_json: dict,
    reason: str | None = None,
    hours: int = 24,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    row = await governance_apply.create_memory_lock(
        session,
        ctx,
        lock_type=lock_type,
        target_type=target_type,
        target_ref_json=target_ref_json,
        reason=reason,
        hours=hours,
    )
    return ApiResponse(data={"id": row.id, "lock_type": row.lock_type})


@router.post("/locks/{lock_id}/release", response_model=ApiResponse)
async def release_lock(
    lock_id: int,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    await governance_apply.release_memory_lock(session, ctx, lock_id)
    return ApiResponse(message="released")


@router.post("/proposals", response_model=ApiResponse)
async def create_proposal(
    target_type: str,
    action: str,
    target_ref_json: dict,
    payload_json: dict,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    proposal_uuid = str(uuid.uuid4())
    row = GovernanceProposal(
        proposal_uuid=proposal_uuid,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        target_type=target_type,
        action=action,
        target_ref_json=target_ref_json,
        payload_json=payload_json,
        status="pending_review",
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    return ApiResponse(data={"proposal_uuid": proposal_uuid})


@router.get("/dreaming/jobs", response_model=ApiResponse)
async def list_dreaming_jobs(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:read")),
) -> ApiResponse:
    rows = (
        await session.execute(
            select(DreamingJob).where(
                DreamingJob.tenant_id == ctx.tenant_id,
                DreamingJob.deleted == 0,
            )
        )
    ).scalars().all()
    return ApiResponse(
        data=[
            {
                "id": r.id,
                "job_name": r.job_name,
                "tier": r.tier,
                "engine": r.engine,
                "status": r.status,
            }
            for r in rows
        ]
    )


@router.post("/dreaming/jobs/{job_id}/runs", response_model=ApiResponse)
async def trigger_dreaming_job_run(
    job_id: int,
    wait: bool = False,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:write")),
) -> ApiResponse:
    """Start a Dreaming job run via Temporal."""
    data = await gov_service.trigger_dreaming_run(session, ctx, job_id, wait=wait)
    return ApiResponse(data=data)


@router.get("/dreaming/runs/{run_uuid}", response_model=ApiResponse)
async def get_dreaming_job_run(
    run_uuid: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("governance:read")),
) -> ApiResponse:
    row = await gov_service.get_dreaming_run(session, ctx, run_uuid)
    return ApiResponse(
        data={
            "run_uuid": row.run_uuid,
            "job_id": row.job_id,
            "status": row.status,
            "temporal_workflow_id": row.temporal_workflow_id,
            "temporal_run_id": row.temporal_run_id,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "stats_json": row.stats_json,
            "failure_reason": row.failure_reason,
        }
    )
