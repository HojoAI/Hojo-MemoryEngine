"""Dreaming job run Temporal workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from memory_engine.temporal.activities.dreaming_activities import (
        dreaming_execute_analytics,
        dreaming_finalize_run,
        dreaming_update_run_status,
    )
    from memory_engine.temporal.params import DreamingRunInput


@workflow.defn(name="DreamingJobRunWorkflow")
class DreamingJobRunWorkflow:
    """Orchestrate LIGHT/REM/DEEP dreaming runs."""

    @workflow.run
    async def run(self, payload: DreamingRunInput) -> dict:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(minutes=1),
            maximum_attempts=3,
        )
        try:
            await workflow.execute_activity(
                dreaming_update_run_status,
                args=[payload.run_uuid, "running"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            stats = await workflow.execute_activity(
                dreaming_execute_analytics,
                payload,
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=retry,
            )
            return await workflow.execute_activity(
                dreaming_finalize_run,
                args=[payload.run_uuid, stats],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
        except Exception as exc:
            await workflow.execute_activity(
                dreaming_update_run_status,
                args=[payload.run_uuid, "failed", str(exc)[:1024], None],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            raise
