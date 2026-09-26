"""P0/P1 atomic memory and policy-first retrieval routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import get_request_context, require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.schemas.common import ApiResponse
from memory_engine.schemas.memory_claim import (
    MemoryCallV2Request,
    MemoryClaimResolveRequest,
    MemoryClaimRevokeRequest,
    MemoryIngestRequest,
    MemoryRetrieveV2Request,
)
from memory_engine.services import memory_claim, memory_v2_retrieve

router = APIRouter(prefix="/memory", tags=["memory-v2"])


@router.post("/ingest", response_model=ApiResponse)
async def ingest_memory(
    body: MemoryIngestRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("memory:claim:write")),
) -> ApiResponse:
    return ApiResponse(data=await memory_claim.ingest(session, ctx, body))


@router.post("/retrieve", response_model=ApiResponse)
async def retrieve_memory(
    body: MemoryRetrieveV2Request,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> ApiResponse:
    return ApiResponse(data=await memory_v2_retrieve.retrieve(session, ctx, body))


@router.post("/call", response_model=ApiResponse)
async def call_memory(
    body: MemoryCallV2Request,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> ApiResponse:
    return ApiResponse(data=await memory_v2_retrieve.call(session, ctx, body))


@router.get("/claims/{claim_id}/history", response_model=ApiResponse)
async def claim_history(
    claim_id: str,
    ctx: RequestContext = Depends(require_permission("memory:claim:review")),
) -> ApiResponse:
    identity_id, items = await memory_claim.history(ctx, claim_id)
    return ApiResponse(data={"identity_id": identity_id, "items": items})


@router.post("/claims/{claim_id}/revoke", response_model=ApiResponse)
async def revoke_claim(
    claim_id: str,
    body: MemoryClaimRevokeRequest,
    ctx: RequestContext = Depends(require_permission("memory:claim:review")),
) -> ApiResponse:
    await memory_claim.revoke(ctx, claim_id, body)
    return ApiResponse(message="revoked")


@router.post("/claims/{claim_id}/resolve", response_model=ApiResponse)
async def resolve_claim(
    claim_id: str,
    body: MemoryClaimResolveRequest,
    ctx: RequestContext = Depends(require_permission("memory:claim:review")),
) -> ApiResponse:
    await memory_claim.resolve_conflict(ctx, claim_id, body)
    return ApiResponse(message="resolved")
