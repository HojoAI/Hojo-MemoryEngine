"""Schema upsert Temporal workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from memory_engine.temporal.activities.schema_activities import schema_upsert_activity
    from memory_engine.temporal.params import SchemaUpsertInput


@workflow.defn(name="SchemaUpsertWorkflow")
class SchemaUpsertWorkflow:
    """Orchestrate schema upsert with retries and compensation-friendly steps."""

    @workflow.run
    async def run(self, payload: SchemaUpsertInput) -> dict:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=5,
        )
        return await workflow.execute_activity(
            schema_upsert_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry,
        )
