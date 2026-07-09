"""Schema-related Temporal activities."""

from typing import Any

from temporalio import activity

from memory_engine.core.context import RequestContext
from memory_engine.db.session import SessionLocal
from memory_engine.schemas.memory_field import MemoryFieldCreate, MemoryFieldOut, MemoryFieldUpdate
from memory_engine.services import memory_field as mf_service
from memory_engine.temporal.params import SchemaUpsertInput


@activity.defn(name="schema_upsert")
async def schema_upsert_activity(payload: SchemaUpsertInput) -> dict[str, Any]:
    """Create or version-update a memory_field inside a DB transaction."""
    ctx = RequestContext(
        tenant_id=payload.tenant_id,
        org_id=payload.org_id,
        user_id=payload.user_id,
    )
    create_body = MemoryFieldCreate.model_validate(payload.create_payload)
    update_body = (
        MemoryFieldUpdate.model_validate(payload.update_payload)
        if payload.update_payload
        else MemoryFieldUpdate()
    )

    async with SessionLocal() as session:
        existing = await mf_service.get_active_by_name(session, ctx, payload.name)
        if existing:
            needs_update = (
                (update_body.value_type and update_body.value_type != existing.value_type)
                or (update_body.match_method and update_body.match_method != existing.match_method)
                or (update_body.storage_type and update_body.storage_type != existing.storage_type)
                or (update_body.description is not None and update_body.description != existing.description)
                or (update_body.status and update_body.status != existing.status)
            )
            if needs_update:
                result = await mf_service.update(session, ctx, payload.name, update_body)
            else:
                result = MemoryFieldOut.model_validate(existing)
        else:
            if create_body.name != payload.name:
                create_body = create_body.model_copy(update={"name": payload.name})
            result = await mf_service.create(session, ctx, create_body)
    return result.model_dump()
