"""Temporal worker entrypoint.

Run: ``poetry run memory-engine-worker`` or ``python -m memory_engine.temporal.worker``
"""

import asyncio

from temporalio.worker import Worker

from memory_engine.config import get_settings
from memory_engine.integrations.temporal_client import get_temporal_client
from memory_engine.temporal.activities.dreaming_activities import (
    dreaming_execute_analytics,
    dreaming_finalize_run,
    dreaming_update_run_status,
)
from memory_engine.temporal.activities.data_activities import data_write_activity
from memory_engine.temporal.activities.schema_activities import schema_upsert_activity
from memory_engine.temporal.activities.dsl_activities import dsl_run_pipeline
from memory_engine.temporal.activities.schema_crud_activities import schema_crud_activity
from memory_engine.temporal.constants import TASK_QUEUE
from memory_engine.temporal.workflows.data_write_workflow import DataWriteWorkflow
from memory_engine.temporal.workflows.dreaming_workflow import DreamingJobRunWorkflow
from memory_engine.temporal.workflows.schema_crud_workflow import SchemaCrudWorkflow
from memory_engine.temporal.workflows.dsl_workflow import DslPipelineWorkflow
from memory_engine.temporal.workflows.schema_workflow import SchemaUpsertWorkflow


async def run_worker() -> None:
    """Poll Temporal task queue and execute workflows/activities."""
    settings = get_settings()
    client = await get_temporal_client()
    task_queue = settings.temporal_task_queue or TASK_QUEUE
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[
            SchemaUpsertWorkflow,
            SchemaCrudWorkflow,
            DataWriteWorkflow,
            DreamingJobRunWorkflow,
            DslPipelineWorkflow,
        ],
        activities=[
            schema_upsert_activity,
            schema_crud_activity,
            data_write_activity,
            dsl_run_pipeline,
            dreaming_update_run_status,
            dreaming_execute_analytics,
            dreaming_finalize_run,
        ],
    )
    print(f"MemoryEngine Temporal worker listening on queue={task_queue!r}")
    await worker.run()


def main() -> None:
    """CLI entry."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
