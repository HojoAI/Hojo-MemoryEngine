"""Capability registry API (/capability/*)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.schemas.capability import CapabilityHeartbeatBody, CapabilityOut, CapabilityRegisterBody
from memory_engine.schemas.common import ApiResponse
from memory_engine.services import capability_registry as cap_service
from memory_engine.services import capability_scan

router = APIRouter(prefix="/capability", tags=["capability"])


@router.post("/register", response_model=ApiResponse)
async def capability_register(
    body: CapabilityRegisterBody,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    """Runtime register capability (module/service binding)."""
    return ApiResponse(data=await cap_service.register(session, ctx, body))


@router.post("/heartbeat", response_model=ApiResponse)
async def capability_heartbeat(
    body: CapabilityHeartbeatBody,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    return ApiResponse(
        data=await cap_service.heartbeat(
            session,
            ctx,
            capability_name=body.capability_name,
            rule_kind=body.rule_kind,
            code_fingerprint=body.code_fingerprint,
        )
    )


@router.get("/get", response_model=ApiResponse)
async def capability_get(
    capability_name: str,
    rule_kind: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    out = await cap_service.get_capability(session, ctx, capability_name, rule_kind)
    return ApiResponse(data=out)


@router.get("/list", response_model=ApiResponse)
async def capability_list(
    rule_kind: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    return ApiResponse(data=await cap_service.list_capabilities(session, ctx, rule_kind=rule_kind, limit=limit))


@router.get("/scan/stale", response_model=ApiResponse)
async def scan_stale_capabilities(
    stale_hours: int = 72,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    """Offline scan: capabilities without recent SDK heartbeat."""
    return ApiResponse(
        data=await capability_scan.scan_stale_capabilities(
            session, ctx, stale_hours=stale_hours
        )
    )


@router.post("/delete", response_model=ApiResponse)
async def capability_delete(
    capability_name: str,
    rule_kind: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    await cap_service.delete_soft(session, ctx, capability_name, rule_kind)
    return ApiResponse(message="deleted")
