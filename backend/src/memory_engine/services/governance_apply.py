"""Governance proposal approval, apply, rollback, memory locks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from memory_engine.models.governance import GovernanceProposal, MemoryLock, ProposalApproval, WritebackAudit
from memory_engine.schemas.memory_field import MemoryFieldCreate, MemoryFieldUpdate
from memory_engine.services import memory_field as mf_service
from memory_engine.services import memory_data as data_service
from memory_engine.schemas.memory_field import MemoryDataCreate, MemoryDataUpdate


async def approve_proposal(
    session: AsyncSession,
    ctx: RequestContext,
    proposal_uuid: str,
    *,
    decision: str = "approved",
    comment: str | None = None,
) -> GovernanceProposal:
    row = await _get_proposal(session, ctx, proposal_uuid)
    if row.status not in ("pending_review", "draft"):
        raise ConflictError(f"proposal status is {row.status}")
    approval = ProposalApproval(
        proposal_id=row.id,
        approver_user_id=ctx.user_id or 0,
        decision=decision,
        comment=comment,
        decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(approval)
    row.status = "approved" if decision == "approved" else "rejected"
    row.updated_by = ctx.user_id
    await session.commit()
    await session.refresh(row)
    return row


async def apply_proposal(
    session: AsyncSession, ctx: RequestContext, proposal_uuid: str
) -> dict:
    """Apply approved proposal via Schema/Data API services."""
    row = await _get_proposal(session, ctx, proposal_uuid)
    if row.status != "approved":
        raise ForbiddenError("proposal must be approved before apply")
    if await _is_locked(session, ctx, row):
        raise ForbiddenError("target is locked")

    payload = row.payload_json or {}
    result: dict
    endpoint = ""

    if row.target_type == "memory_field":
        name = payload.get("name") or row.target_ref_json.get("name")
        if row.action == "create":
            endpoint = "/schema/create"
            result = (
                await mf_service.create(
                    session, ctx, MemoryFieldCreate(**payload)
                )
            ).model_dump()
        elif row.action == "update":
            endpoint = "/schema/update"
            result = (
                await mf_service.update(
                    session, ctx, name, MemoryFieldUpdate(**payload)
                )
            ).model_dump()
        elif row.action == "delete":
            endpoint = "/schema/delete"
            await mf_service.delete_soft(session, ctx, name)
            result = {"deleted": name}
        else:
            raise ConflictError(f"unsupported action {row.action}")
    elif row.target_type == "memory_data":
        if row.action == "create":
            endpoint = "/data/create"
            body = MemoryDataCreate(**payload)
            out = await data_service.create(session, ctx, body)
            result = out.model_dump()
        elif row.action == "update":
            endpoint = "/data/update"
            body = MemoryDataUpdate(**payload)
            out = await data_service.update(session, ctx, body)
            result = out.model_dump()
        elif row.action == "delete":
            endpoint = "/data/delete"
            await data_service.delete_soft(
                session, ctx, payload["user_id"], payload["memory_field_name"]
            )
            result = {"deleted": True}
        else:
            raise ConflictError(f"unsupported action {row.action}")
    else:
        raise ConflictError(f"unsupported target_type {row.target_type}")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    audit = WritebackAudit(
        proposal_id=row.id,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        api_endpoint=endpoint,
        target_type=row.target_type,
        request_payload_json=payload,
        response_payload_json=result,
        status="succeeded",
        rollback_deadline=now + timedelta(hours=24),
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(audit)
    row.status = "applied"
    row.applied_at = now
    row.updated_by = ctx.user_id
    await session.commit()
    return {"proposal_uuid": proposal_uuid, "status": "applied", "result": result}


async def create_memory_lock(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    lock_type: str,
    target_type: str,
    target_ref_json: dict,
    reason: str | None = None,
    hours: int = 24,
) -> MemoryLock:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = MemoryLock(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        lock_type=lock_type,
        target_type=target_type,
        target_ref_json=target_ref_json,
        locked_by_user_id=ctx.user_id or 0,
        reason=reason,
        expires_at=now + timedelta(hours=hours),
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def release_memory_lock(
    session: AsyncSession, ctx: RequestContext, lock_id: int
) -> None:
    result = await session.execute(
        select(MemoryLock).where(
            MemoryLock.id == lock_id,
            MemoryLock.tenant_id == ctx.tenant_id,
            MemoryLock.deleted == 0,
            MemoryLock.released_at.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("lock not found")
    row.released_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.updated_by = ctx.user_id
    await session.commit()


async def _get_proposal(
    session: AsyncSession, ctx: RequestContext, proposal_uuid: str
) -> GovernanceProposal:
    result = await session.execute(
        select(GovernanceProposal).where(
            GovernanceProposal.proposal_uuid == proposal_uuid,
            GovernanceProposal.tenant_id == ctx.tenant_id,
            GovernanceProposal.deleted == 0,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("proposal not found")
    return row


async def _is_locked(
    session: AsyncSession, ctx: RequestContext, proposal: GovernanceProposal
) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        select(MemoryLock).where(
            MemoryLock.tenant_id == ctx.tenant_id,
            MemoryLock.deleted == 0,
            MemoryLock.released_at.is_(None),
            MemoryLock.expires_at > now,
        )
    )
    locks = list(result.scalars().all())
    ref = proposal.target_ref_json or {}
    for lock in locks:
        lref = lock.target_ref_json or {}
        if lock.target_type == proposal.target_type and lref.get("name") == ref.get("name"):
            return True
    return False


async def create_proposal_from_dreaming(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    job_run_id: int | None,
    target_type: str,
    action: str,
    target_ref_json: dict,
    payload_json: dict,
    confidence_score: float,
    risk_level: str,
    evidence_json: dict | None = None,
) -> str:
    """Create governance proposal with confidence scoring."""
    proposal_uuid = str(uuid.uuid4())
    auto_apply = 1 if confidence_score >= 0.9 and risk_level == "low" else 0
    status = "approved" if auto_apply else "pending_review"
    row = GovernanceProposal(
        proposal_uuid=proposal_uuid,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        job_run_id=job_run_id,
        target_type=target_type,
        action=action,
        target_ref_json=target_ref_json,
        payload_json=payload_json,
        evidence_json=evidence_json,
        confidence_score=Decimal(str(confidence_score)),
        risk_level=risk_level,
        status=status,
        auto_apply=auto_apply,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    if auto_apply:
        await approve_proposal(session, ctx, proposal_uuid, decision="approved")
        await apply_proposal(session, ctx, proposal_uuid)
    return proposal_uuid
