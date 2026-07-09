"""Temporal activities for schema CRUD."""

from typing import Any

from temporalio import activity

from memory_engine.core.context import RequestContext
from memory_engine.db.session import SessionLocal
from memory_engine.schemas.memory_field import MemoryFieldCreate, MemoryFieldUpdate
from memory_engine.services import memory_field as mf_service
from memory_engine.temporal.params import SchemaCrudInput


@activity.defn(name="schema_crud")
async def schema_crud_activity(payload: SchemaCrudInput) -> dict[str, Any]:
    ctx = RequestContext(
        tenant_id=payload.tenant_id,
        org_id=payload.org_id,
        user_id=payload.user_id,
    )
    async with SessionLocal() as session:
        if payload.operation == "create":
            body = MemoryFieldCreate.model_validate(payload.create_payload or {})
            out = await mf_service.create(session, ctx, body)
            return out.model_dump()
        if payload.operation == "update":
            body = MemoryFieldUpdate.model_validate(payload.update_payload or {})
            out = await mf_service.update(session, ctx, payload.name, body)
            return out.model_dump()
        if payload.operation == "delete":
            await mf_service.delete_soft(session, ctx, payload.name)
            return {"deleted": payload.name}
    raise ValueError(f"unknown operation: {payload.operation}")
