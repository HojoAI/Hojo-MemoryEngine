"""M13 memory candidate preview APIs."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.schemas.common import ApiResponse
from memory_engine.schemas.memory_candidate import (
    MemoryCandidateCompareRequest,
    MemoryCandidateExtractRequest,
)
from memory_engine.services import memory_candidate

router = APIRouter(prefix="/memory/candidates", tags=["memory-candidates"])


@router.post("/extract", response_model=ApiResponse)
async def extract_memory_candidates(
    body: MemoryCandidateExtractRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    """Extract categorized M13 candidates without writing memory."""
    out = await memory_candidate.extract_candidates(session, ctx, body)
    return ApiResponse(data=out.model_dump(by_alias=True, exclude_none=True))


@router.post("/compare", response_model=ApiResponse)
async def compare_memory_candidate(
    body: MemoryCandidateCompareRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    """Compare one candidate with the user's current claims without modifying them."""
    out = await memory_candidate.compare_candidate(session, ctx, body)
    return ApiResponse(data=out.model_dump(by_alias=True, exclude_none=True))
