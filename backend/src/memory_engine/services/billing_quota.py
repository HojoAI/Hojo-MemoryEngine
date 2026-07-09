"""Usage quota, cost aggregation, and billing invoices."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from memory_engine.models.billing import BillingEvent, BillingInvoice, UsageQuota


async def check_and_consume_quota(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    amount: Decimal,
    quota_type: str = "tokens",
) -> None:
    """Raise if tenant monthly token/cost quota exceeded; otherwise increment usage."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        select(UsageQuota).where(
            UsageQuota.tenant_id == ctx.tenant_id,
            UsageQuota.scope == "tenant",
            UsageQuota.target_id == ctx.tenant_id,
            UsageQuota.quota_type == quota_type,
            UsageQuota.period == "monthly",
            UsageQuota.deleted == 0,
            UsageQuota.status == "active",
            UsageQuota.period_start <= now,
            UsageQuota.period_end > now,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return
    if row.quota_used + amount > row.quota_limit:
        row.status = "exceeded"
        await session.commit()
        raise ForbiddenError(f"quota exceeded for {quota_type}")
    row.quota_used = row.quota_used + amount
    await session.commit()


async def create_quota(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    scope: str,
    target_id: int,
    quota_type: str,
    period: str,
    quota_limit: Decimal,
    period_start: datetime,
    period_end: datetime,
) -> UsageQuota:
    row = UsageQuota(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        scope=scope,
        target_id=target_id,
        quota_type=quota_type,
        period=period,
        quota_limit=quota_limit,
        period_start=period_start,
        period_end=period_end,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def usage_summary(
    session: AsyncSession, ctx: RequestContext, *, days: int = 30
) -> dict:
    """Token and cost summary for dashboard."""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    result = await session.execute(
        select(
            func.coalesce(func.sum(BillingEvent.total_tokens), 0),
            func.coalesce(func.sum(BillingEvent.cost_amount), 0),
            func.count(BillingEvent.id),
        ).where(
            BillingEvent.tenant_id == ctx.tenant_id,
            BillingEvent.deleted == 0,
            BillingEvent.occurred_at >= since,
        )
    )
    tokens, cost, count = result.one()
    return {
        "total_tokens": int(tokens or 0),
        "total_cost": float(cost or 0),
        "event_count": int(count or 0),
        "currency": "CNY",
    }


async def generate_monthly_invoice(
    session: AsyncSession, ctx: RequestContext, period_month: str
) -> BillingInvoice:
    """Aggregate billing events into monthly invoice."""
    existing = await session.execute(
        select(BillingInvoice).where(
            BillingInvoice.tenant_id == ctx.tenant_id,
            BillingInvoice.org_id == ctx.org_id,
            BillingInvoice.period_month == period_month,
            BillingInvoice.deleted == 0,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"invoice for {period_month} already exists")

    agg = await session.execute(
        select(
            func.coalesce(func.sum(BillingEvent.total_tokens), 0),
            func.coalesce(func.sum(BillingEvent.cost_amount), 0),
        ).where(
            BillingEvent.tenant_id == ctx.tenant_id,
            BillingEvent.org_id == ctx.org_id,
            BillingEvent.deleted == 0,
            func.date_format(BillingEvent.occurred_at, "%Y-%m") == period_month,
        )
    )
    total_tokens, total_amount = agg.one()
    row = BillingInvoice(
        invoice_uuid=str(uuid.uuid4()),
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        period_month=period_month,
        total_tokens=int(total_tokens or 0),
        total_amount=Decimal(total_amount or 0),
        status="issued",
        issued_at=datetime.now(timezone.utc).replace(tzinfo=None),
        details_json={"generated_by": "api"},
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_invoices(
    session: AsyncSession, ctx: RequestContext, limit: int = 12
) -> list[BillingInvoice]:
    result = await session.execute(
        select(BillingInvoice)
        .where(BillingInvoice.tenant_id == ctx.tenant_id, BillingInvoice.deleted == 0)
        .order_by(BillingInvoice.period_month.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
