"""High-level DSL orchestration API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.dsl.engine import DslEngine, DslPipeline
from memory_engine.schemas.common import ApiResponse
from memory_engine.services.workflow_launch import launch_dsl_pipeline

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


@router.post("/dsl/run", response_model=ApiResponse)
async def run_dsl_pipeline(
    pipeline: DslPipeline,
    use_temporal: bool = False,
    wait: bool = True,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    """Run DSL pipeline in-process or via Temporal."""
    if use_temporal:
        data = await launch_dsl_pipeline(ctx, pipeline, wait=wait)
        return ApiResponse(data=data)
    engine = DslEngine()
    results = await engine.run_pipeline(session, ctx, pipeline)
    return ApiResponse(data=[r.model_dump() if hasattr(r, "model_dump") else r for r in results])
