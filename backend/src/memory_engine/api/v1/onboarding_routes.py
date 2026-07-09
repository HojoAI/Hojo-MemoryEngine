"""Dashboard onboarding: API key apply, tenant bootstrap helpers."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from memory_engine.api.deps import get_request_context, require_permission
from memory_engine.models.auth import ApiKey
from memory_engine.api.v1.admin_routes import verify_bootstrap_secret
from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.db.session import get_db
from memory_engine.schemas.admin import TenantBootstrapRequest, TenantBootstrapResponse
from memory_engine.schemas.common import ApiResponse
from memory_engine.schemas.onboarding import (
    ApiKeyApplyRequest,
    ApiKeyCreateRequest,
    ApiKeyIssueResponse,
)
from memory_engine.services import admin_service, onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _require_supabase_user_id(
    x_supabase_user_id: str | None = Header(None, alias="X-Supabase-User-Id"),
) -> str:
    if not x_supabase_user_id or len(x_supabase_user_id.strip()) < 8:
        raise ForbiddenError("X-Supabase-User-Id required")
    return x_supabase_user_id.strip()


@router.get("/session", response_model=ApiResponse)
async def onboarding_session(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(get_request_context),
) -> ApiResponse:
    """Resolve Bearer API key to prefix + memory partition id (SDK validation)."""
    if ctx.api_key_id is None:
        raise ForbiddenError("Bearer API key required")
    row = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.id == ctx.api_key_id,
                ApiKey.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise ForbiddenError("API key not found")
    return ApiResponse(
        data={
            "key_prefix": row.key_prefix,
            "app_user_id": row.user_id,
            "memory_user_id": row.key_prefix,
            "tenant_id": ctx.tenant_id,
            "org_id": ctx.org_id,
            "valid": row.revoked_at is None,
            "api_key_id": row.id,
        }
    )


@router.get("/me", response_model=ApiResponse)
async def onboarding_me(
    session: AsyncSession = Depends(get_db),
    supabase_user_id: str = Depends(_require_supabase_user_id),
) -> ApiResponse:
    """Profile + API key prefixes for the logged-in Supabase user (no Bearer required)."""
    profile = await onboarding_service.get_profile_by_supabase(session, supabase_user_id)
    return ApiResponse(data=profile.model_dump())


@router.post("/api-key/apply", response_model=ApiResponse)
async def apply_api_key(
    body: ApiKeyApplyRequest,
    session: AsyncSession = Depends(get_db),
    supabase_user_id: str = Depends(_require_supabase_user_id),
) -> ApiResponse:
    """Register/link Supabase user and return a new API key (plaintext once)."""
    settings = get_settings()
    if not settings.onboarding_allow_self_register:
        raise ForbiddenError("Self-service onboarding is disabled")

    email = (body.email or "").strip()
    if not email:
        raise ForbiddenError("email is required for API key application")

    issued: ApiKeyIssueResponse = await onboarding_service.apply_api_key_for_supabase(
        session,
        supabase_user_id=supabase_user_id,
        email=email,
        display_name=body.display_name,
        key_name=body.name,
    )
    return ApiResponse(data=issued.model_dump())


@router.get("/api-keys", response_model=ApiResponse)
async def list_api_keys(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("api_key:manage")),
) -> ApiResponse:
    """List API keys for the current authenticated user."""
    rows = await onboarding_service.list_api_keys_for_context(session, ctx)
    return ApiResponse(data=[r.model_dump() for r in rows])


@router.post("/api-keys", response_model=ApiResponse)
async def create_api_key(
    body: ApiKeyCreateRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("api_key:manage")),
) -> ApiResponse:
    """Create an additional API key for the current user."""
    issued = await onboarding_service.create_api_key_for_context(session, ctx, body.name)
    return ApiResponse(data=issued.model_dump())


@router.post("/tenant", response_model=ApiResponse)
async def create_tenant(
    body: TenantBootstrapRequest,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_bootstrap_secret),
) -> ApiResponse:
    """Create tenant + org + user + API key (admin secret). Same as POST /admin/tenants."""
    data: TenantBootstrapResponse = await admin_service.bootstrap_tenant(session, body)
    return ApiResponse(data=data.model_dump())
