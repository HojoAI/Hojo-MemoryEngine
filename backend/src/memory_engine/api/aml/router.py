"""Agent Memory Leaderboard protocol routes."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from memory_engine.api.deps import get_aml_request_context
from memory_engine.core.context import RequestContext
from memory_engine.schemas.aml import (
    AMLAddRequest,
    AMLAddResponse,
    AMLClearRequest,
    AMLClearResponse,
    AMLSearchRequest,
    AMLSearchResponse,
)
from memory_engine.services import aml_adapter

aml_router = APIRouter(prefix="/aml", tags=["aml"])


@aml_router.post("/add", response_model=AMLAddResponse)
async def add_memory(
    body: AMLAddRequest,
    ctx: RequestContext = Depends(get_aml_request_context),
) -> AMLAddResponse:
    return await aml_adapter.add(ctx, body)


@aml_router.post("/search", response_model=AMLSearchResponse)
async def search_memory(
    body: AMLSearchRequest,
    ctx: RequestContext = Depends(get_aml_request_context),
) -> AMLSearchResponse:
    return await aml_adapter.search(ctx, body)


@aml_router.post("/clear", response_model=AMLClearResponse)
async def clear_memory(
    body: AMLClearRequest,
    ctx: RequestContext = Depends(get_aml_request_context),
) -> AMLClearResponse:
    """Operational cleanup endpoint; it is not used by the formal evaluator."""
    return await aml_adapter.clear(ctx, body.user_id)


@aml_router.get("/health")
async def aml_health() -> JSONResponse:
    result = await aml_adapter.health()
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)
