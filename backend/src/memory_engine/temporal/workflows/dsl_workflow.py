"""DSL orchestration workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from memory_engine.temporal.activities.dsl_activities import dsl_run_pipeline


@workflow.defn(name="DslPipelineWorkflow")
class DslPipelineWorkflow:
    @workflow.run
    async def run(
        self, tenant_id: int, org_id: int, user_id: int | None, pipeline_dict: dict
    ) -> list:
        return await workflow.execute_activity(
            dsl_run_pipeline,
            args=[tenant_id, org_id, user_id, pipeline_dict],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
