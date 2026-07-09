"""DSL pipeline Temporal activity."""

from temporalio import activity

from memory_engine.db.session import SessionLocal
from memory_engine.dsl.engine import DslEngine, DslPipeline
from memory_engine.core.context import RequestContext


@activity.defn(name="dsl_run_pipeline")
async def dsl_run_pipeline(
    tenant_id: int,
    org_id: int,
    user_id: int | None,
    pipeline_dict: dict,
) -> list:
    """Execute DSL pipeline steps."""
    pipeline = DslPipeline.model_validate(pipeline_dict)
    ctx = RequestContext(tenant_id=tenant_id, org_id=org_id, user_id=user_id)
    engine = DslEngine()
    async with SessionLocal() as session:
        results = await engine.run_pipeline(session, ctx, pipeline)
    return [r.model_dump() if hasattr(r, "model_dump") else r for r in results]
