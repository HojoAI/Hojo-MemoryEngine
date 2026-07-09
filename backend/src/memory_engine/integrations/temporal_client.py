"""Temporal client helpers."""

from temporalio.client import Client, WorkflowHandle

from memory_engine.config import get_settings
from memory_engine.temporal.constants import DREAMING_JOB_RUN_WORKFLOW, SCHEMA_UPSERT_WORKFLOW, TASK_QUEUE
from memory_engine.temporal.params import DataWriteInput, DreamingRunInput, SchemaCrudInput, SchemaUpsertInput
from memory_engine.temporal.workflows.data_write_workflow import DataWriteWorkflow
from memory_engine.temporal.workflows.dreaming_workflow import DreamingJobRunWorkflow
from memory_engine.temporal.workflows.schema_crud_workflow import SchemaCrudWorkflow
from memory_engine.temporal.workflows.dsl_workflow import DslPipelineWorkflow
from memory_engine.temporal.workflows.schema_workflow import SchemaUpsertWorkflow

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Lazy Temporal client (connects to TEMPORAL_HOST)."""
    global _client
    if _client is None:
        settings = get_settings()
        target = settings.temporal_host
        if not target.startswith("http"):
            target = f"{target}:7233" if ":" not in target else target
        _client = await Client.connect(target, namespace=settings.temporal_namespace)
    return _client


async def start_schema_upsert_workflow(
    payload: SchemaUpsertInput,
    *,
    workflow_id: str,
) -> WorkflowHandle:
    """Start SchemaUpsertWorkflow."""
    client = await get_temporal_client()
    return await client.start_workflow(
        SchemaUpsertWorkflow.run,
        payload,
        id=workflow_id,
        task_queue=get_settings().temporal_task_queue or TASK_QUEUE,
    )


async def start_schema_crud_workflow(payload: SchemaCrudInput, *, workflow_id: str) -> WorkflowHandle:
    client = await get_temporal_client()
    return await client.start_workflow(
        SchemaCrudWorkflow.run,
        payload,
        id=workflow_id,
        task_queue=get_settings().temporal_task_queue or TASK_QUEUE,
    )


async def start_data_write_workflow(payload: DataWriteInput, *, workflow_id: str) -> WorkflowHandle:
    client = await get_temporal_client()
    return await client.start_workflow(
        DataWriteWorkflow.run,
        payload,
        id=workflow_id,
        task_queue=get_settings().temporal_task_queue or TASK_QUEUE,
    )


async def start_dsl_pipeline_workflow(
    tenant_id: int,
    org_id: int,
    user_id: int | None,
    pipeline_dict: dict,
    *,
    workflow_id: str,
) -> WorkflowHandle:
    client = await get_temporal_client()
    return await client.start_workflow(
        DslPipelineWorkflow.run,
        args=[tenant_id, org_id, user_id, pipeline_dict],
        id=workflow_id,
        task_queue=get_settings().temporal_task_queue or TASK_QUEUE,
    )


async def start_dreaming_run_workflow(
    payload: DreamingRunInput,
    *,
    workflow_id: str,
) -> WorkflowHandle:
    """Start DreamingJobRunWorkflow."""
    client = await get_temporal_client()
    return await client.start_workflow(
        DreamingJobRunWorkflow.run,
        payload,
        id=workflow_id,
        task_queue=get_settings().temporal_task_queue or TASK_QUEUE,
    )


def workflow_type_name(kind: str) -> str:
    """Map internal kind to Temporal workflow type name."""
    if kind == "schema_upsert":
        return SCHEMA_UPSERT_WORKFLOW
    if kind == "dreaming_run":
        return DREAMING_JOB_RUN_WORKFLOW
    return kind
