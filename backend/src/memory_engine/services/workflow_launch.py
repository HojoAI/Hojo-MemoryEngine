"""Start Temporal workflows and return handles."""

import asyncio
import uuid

from temporalio.client import WorkflowFailureError

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError
from memory_engine.dsl.engine import DslPipeline
from memory_engine.integrations.temporal_client import (
    start_data_write_workflow,
    start_dreaming_run_workflow,
    start_dsl_pipeline_workflow,
    start_schema_crud_workflow,
    start_schema_upsert_workflow,
)
from memory_engine.schemas.memory_field import MemoryDataCreate, MemoryFieldCreate, MemoryFieldUpdate
from memory_engine.temporal.params import DataWriteInput, DreamingRunInput, SchemaCrudInput, SchemaUpsertInput


async def launch_schema_upsert(
    ctx: RequestContext,
    body: MemoryFieldCreate,
    *,
    wait: bool = False,
    wait_timeout_sec: float = 120.0,
) -> dict:
    """Enqueue SchemaUpsertWorkflow; optionally block until completion."""
    workflow_id = f"schema-upsert-{ctx.tenant_id}-{ctx.org_id}-{body.name}-{uuid.uuid4().hex[:8]}"
    update_payload = MemoryFieldUpdate(
        description=body.description,
        value_type=body.value_type,
        match_method=body.match_method,
        storage_type=body.storage_type,
    )
    payload = SchemaUpsertInput(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        name=body.name,
        create_payload=body.model_dump(),
        update_payload=update_payload.model_dump(exclude_none=True),
    )
    handle = await start_schema_upsert_workflow(payload, workflow_id=workflow_id)
    desc = await handle.describe()
    result: dict = {
        "workflow_id": workflow_id,
        "run_id": desc.run_id,
        "status": "started",
    }
    if wait:
        try:
            result["result"] = await asyncio.wait_for(handle.result(), timeout=wait_timeout_sec)
            result["status"] = "completed"
        except WorkflowFailureError as exc:
            raise ConflictError(f"Schema upsert workflow failed: {exc}") from exc
    return result


async def launch_schema_crud(
    ctx: RequestContext,
    operation: str,
    name: str,
    *,
    create_body: MemoryFieldCreate | None = None,
    update_body: MemoryFieldUpdate | None = None,
    wait: bool = False,
    wait_timeout_sec: float = 120.0,
) -> dict:
    workflow_id = f"schema-{operation}-{ctx.tenant_id}-{name}-{uuid.uuid4().hex[:8]}"
    payload = SchemaCrudInput(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        operation=operation,
        name=name,
        create_payload=create_body.model_dump() if create_body else None,
        update_payload=update_body.model_dump(exclude_none=True) if update_body else None,
    )
    handle = await start_schema_crud_workflow(payload, workflow_id=workflow_id)
    desc = await handle.describe()
    result = {"workflow_id": workflow_id, "run_id": desc.run_id, "status": "started"}
    if wait:
        try:
            result["result"] = await asyncio.wait_for(handle.result(), timeout=wait_timeout_sec)
            result["status"] = "completed"
        except WorkflowFailureError as exc:
            raise ConflictError(f"Schema {operation} workflow failed: {exc}") from exc
    return result


async def launch_data_write(
    ctx: RequestContext,
    body: MemoryDataCreate,
    *,
    wait: bool = False,
    wait_timeout_sec: float = 120.0,
) -> dict:
    workflow_id = f"data-write-{ctx.tenant_id}-{body.user_id}-{uuid.uuid4().hex[:8]}"
    payload = DataWriteInput(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        create_payload=body.model_dump(),
    )
    handle = await start_data_write_workflow(payload, workflow_id=workflow_id)
    desc = await handle.describe()
    result = {"workflow_id": workflow_id, "run_id": desc.run_id, "status": "started"}
    if wait:
        try:
            result["result"] = await asyncio.wait_for(handle.result(), timeout=wait_timeout_sec)
            result["status"] = "completed"
        except WorkflowFailureError as exc:
            raise ConflictError(f"Data write workflow failed: {exc}") from exc
    return result


async def launch_dsl_pipeline(
    ctx: RequestContext,
    pipeline: DslPipeline,
    *,
    wait: bool = False,
    wait_timeout_sec: float = 300.0,
) -> dict:
    workflow_id = f"dsl-{ctx.tenant_id}-{uuid.uuid4().hex[:8]}"
    handle = await start_dsl_pipeline_workflow(
        ctx.tenant_id,
        ctx.org_id,
        ctx.user_id,
        pipeline.model_dump(),
        workflow_id=workflow_id,
    )
    desc = await handle.describe()
    result = {"workflow_id": workflow_id, "run_id": desc.run_id, "status": "started"}
    if wait:
        try:
            result["result"] = await asyncio.wait_for(handle.result(), timeout=wait_timeout_sec)
            result["status"] = "completed"
        except WorkflowFailureError as exc:
            raise ConflictError(f"DSL workflow failed: {exc}") from exc
    return result


async def launch_dreaming_run(
    *,
    run_uuid: str,
    workflow_id: str,
    payload: DreamingRunInput,
    wait: bool = False,
    wait_timeout_sec: float = 600.0,
) -> dict:
    """Enqueue DreamingJobRunWorkflow."""
    handle = await start_dreaming_run_workflow(payload, workflow_id=workflow_id)
    desc = await handle.describe()
    out = {
        "workflow_id": workflow_id,
        "run_id": desc.run_id,
        "run_uuid": run_uuid,
        "status": "started",
    }
    if wait:
        try:
            out["result"] = await asyncio.wait_for(handle.result(), timeout=wait_timeout_sec)
            out["status"] = "completed"
        except WorkflowFailureError as exc:
            raise ConflictError(f"Dreaming workflow failed: {exc}") from exc
    return out
