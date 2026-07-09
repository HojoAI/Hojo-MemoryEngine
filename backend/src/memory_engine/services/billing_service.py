"""Billing event emission and async processing."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.integrations.kafka_producer import publish
from memory_engine.models.billing import BillingEvent

# Rough pricing per 1k tokens (CNY) for demo aggregation
_COST_PER_1K_TOKENS = Decimal("0.01")


async def emit_llm_completion(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    trace_id: str | None = None,
) -> str:
    """Persist billing_event and publish to Kafka (non-blocking downstream)."""
    total = prompt_tokens + completion_tokens
    cost = (Decimal(total) / Decimal(1000)) * _COST_PER_1K_TOKENS
    event_uuid = str(uuid.uuid4())
    row = BillingEvent(
        event_uuid=event_uuid,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id or 0,
        api_key_id=ctx.api_key_id,
        event_type="llm_completion",
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        cost_amount=cost,
        status="pending",
        trace_id=trace_id,
        occurred_at=datetime.utcnow(),
    )
    session.add(row)
    await session.commit()

    settings = get_settings()
    if settings.billing_enforce_quota:
        from memory_engine.services import billing_quota

        await billing_quota.check_and_consume_quota(
            session, ctx, amount=Decimal(total), quota_type="tokens"
        )
        await billing_quota.check_and_consume_quota(
            session, ctx, amount=cost, quota_type="cost"
        )

    await publish(
        settings.kafka_billing_events_topic,
        {
            "event_uuid": event_uuid,
            "tenant_id": ctx.tenant_id,
            "org_id": ctx.org_id,
            "event_type": "llm_completion",
            "total_tokens": total,
        },
        key=event_uuid,
    )
    return event_uuid


async def process_billing_event(session: AsyncSession, event_uuid: str) -> bool:
    """Mark billing event processed (Kafka consumer)."""
    result = await session.execute(
        select(BillingEvent).where(
            BillingEvent.event_uuid == event_uuid,
            BillingEvent.deleted == 0,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    if row.status == "processed":
        return True
    await session.execute(
        update(BillingEvent)
        .where(BillingEvent.id == row.id)
        .values(status="processed", processed_at=datetime.utcnow())
    )
    await session.commit()
    return True
