"""Memory data write Temporal workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from memory_engine.temporal.activities.data_activities import data_write_activity
    from memory_engine.temporal.params import DataWriteInput


@workflow.defn(name="DataWriteWorkflow")
class DataWriteWorkflow:
    @workflow.run
    async def run(self, payload: DataWriteInput) -> dict:
        retry = RetryPolicy(maximum_attempts=5)
        return await workflow.execute_activity(
            data_write_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry,
        )
