"""Schema CRUD Temporal workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from memory_engine.temporal.activities.schema_crud_activities import schema_crud_activity
    from memory_engine.temporal.params import SchemaCrudInput


@workflow.defn(name="SchemaCrudWorkflow")
class SchemaCrudWorkflow:
    @workflow.run
    async def run(self, payload: SchemaCrudInput) -> dict:
        retry = RetryPolicy(maximum_attempts=5)
        return await workflow.execute_activity(
            schema_crud_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry,
        )
