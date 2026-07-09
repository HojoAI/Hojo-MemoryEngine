"""Temporal activities for memory data writes."""

from typing import Any

from temporalio import activity

from memory_engine.core.context import RequestContext
from memory_engine.db.session import SessionLocal
from memory_engine.schemas.memory_field import MemoryDataCreate
from memory_engine.services import memory_data as data_service
from memory_engine.temporal.params import DataWriteInput


@activity.defn(name="data_write")
async def data_write_activity(payload: DataWriteInput) -> dict[str, Any]:
    ctx = RequestContext(
        tenant_id=payload.tenant_id,
        org_id=payload.org_id,
        user_id=payload.user_id,
    )
    body = MemoryDataCreate.model_validate(payload.create_payload)
    async with SessionLocal() as session:
        out = await data_service.create(session, ctx, body)
    return out.model_dump()
