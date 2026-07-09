"""Billing API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.models.billing import BillingEvent
from memory_engine.schemas.common import ApiResponse
from decimal import Decimal

from memory_engine.services import billing_service
from memory_engine.services import billing_quota

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/events", response_model=ApiResponse)
async def list_events(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:read")),
) -> ApiResponse:
    result = await session.execute(
        select(BillingEvent)
        .where(BillingEvent.tenant_id == ctx.tenant_id, BillingEvent.deleted == 0)
        .order_by(BillingEvent.occurred_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return ApiResponse(
        data=[
            {
                "event_uuid": r.event_uuid,
                "event_type": r.event_type,
                "total_tokens": r.total_tokens,
                "status": r.status,
            }
            for r in rows
        ]
    )


@router.post("/events/emit", response_model=ApiResponse)
async def emit_event(
    event_type: str,
    total_tokens: int = 0,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:write")),
) -> ApiResponse:
    """Emit billing event (async via Kafka consumer)."""
    if event_type == "llm_completion":
        event_uuid = await billing_service.emit_llm_completion(
            session,
            ctx,
            model_name=None,
            prompt_tokens=total_tokens // 2,
            completion_tokens=total_tokens - total_tokens // 2,
        )
    else:
        from datetime import datetime
        from decimal import Decimal
        import uuid

        event_uuid = str(uuid.uuid4())
        row = BillingEvent(
            event_uuid=event_uuid,
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            user_id=ctx.user_id or 0,
            api_key_id=ctx.api_key_id,
            event_type=event_type,
            total_tokens=total_tokens,
            cost_amount=Decimal("0"),
            status="pending",
            occurred_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()
        from memory_engine.integrations.kafka_producer import publish
        from memory_engine.config import get_settings

        settings = get_settings()
        await publish(
            settings.kafka_billing_events_topic,
            {"event_uuid": event_uuid, "tenant_id": ctx.tenant_id},
            key=event_uuid,
        )
    return ApiResponse(data={"event_uuid": event_uuid})


@router.get("/summary", response_model=ApiResponse)
async def billing_summary(
    days: int = 30,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:read")),
) -> ApiResponse:
    return ApiResponse(data=await billing_quota.usage_summary(session, ctx, days=days))


@router.get("/invoices", response_model=ApiResponse)
async def list_invoices(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:read")),
) -> ApiResponse:
    rows = await billing_quota.list_invoices(session, ctx)
    return ApiResponse(
        data=[
            {
                "invoice_uuid": r.invoice_uuid,
                "period_month": r.period_month,
                "total_tokens": r.total_tokens,
                "total_amount": float(r.total_amount),
                "status": r.status,
            }
            for r in rows
        ]
    )


@router.post("/invoices/generate", response_model=ApiResponse)
async def generate_invoice(
    period_month: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:manage")),
) -> ApiResponse:
    row = await billing_quota.generate_monthly_invoice(session, ctx, period_month)
    return ApiResponse(
        data={
            "invoice_uuid": row.invoice_uuid,
            "period_month": row.period_month,
            "total_amount": float(row.total_amount),
        }
    )


@router.post("/quotas", response_model=ApiResponse)
async def create_quota(
    scope: str,
    target_id: int,
    quota_type: str,
    period: str,
    quota_limit: float,
    period_start: str,
    period_end: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:manage")),
) -> ApiResponse:
    from datetime import datetime

    row = await billing_quota.create_quota(
        session,
        ctx,
        scope=scope,
        target_id=target_id,
        quota_type=quota_type,
        period=period,
        quota_limit=Decimal(str(quota_limit)),
        period_start=datetime.fromisoformat(period_start),
        period_end=datetime.fromisoformat(period_end),
    )
    return ApiResponse(data={"id": row.id, "quota_limit": float(row.quota_limit)})
