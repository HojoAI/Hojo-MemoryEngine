"""Admin bootstrap routes."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.db.session import get_db
from memory_engine.schemas.admin import TenantBootstrapRequest, TenantBootstrapResponse
from memory_engine.schemas.common import ApiResponse
from memory_engine.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


async def verify_bootstrap_secret(
    x_admin_secret: str | None = Header(None, alias="X-Admin-Secret"),
) -> None:
    """Allow bootstrap when secret matches or auth is disabled in dev."""
    settings = get_settings()
    if settings.app_disable_auth:
        return
    if not settings.admin_bootstrap_secret:
        raise ForbiddenError("Admin bootstrap disabled (set ADMIN_BOOTSTRAP_SECRET)")
    if x_admin_secret != settings.admin_bootstrap_secret:
        raise ForbiddenError("Invalid X-Admin-Secret")


@router.post("/tenants", response_model=ApiResponse)
async def bootstrap_tenant(
    body: TenantBootstrapRequest,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_bootstrap_secret),
) -> ApiResponse:
    """Create tenant, organization, user, and API key (one-shot onboarding)."""
    data = await admin_service.bootstrap_tenant(session, body)
    return ApiResponse(data=data)


@router.get("/metrics", response_model=ApiResponse)
async def platform_metrics(
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_bootstrap_secret),
) -> ApiResponse:
    """Basic platform metrics for monitoring dashboard."""
    from sqlalchemy import func, select

    from memory_engine.models.billing import BillingEvent
    from memory_engine.models.schema import MemoryField
    from memory_engine.models.tenant import AppUser, Tenant

    tenants = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
    users = (await session.execute(select(func.count(AppUser.id)))).scalar_one()
    fields = (
        await session.execute(
            select(func.count(MemoryField.id)).where(MemoryField.deleted == 0)
        )
    ).scalar_one()
    events = (
        await session.execute(
            select(func.count(BillingEvent.id)).where(BillingEvent.deleted == 0)
        )
    ).scalar_one()
    return ApiResponse(
        data={
            "tenant_count": int(tenants or 0),
            "user_count": int(users or 0),
            "memory_field_count": int(fields or 0),
            "billing_event_count": int(events or 0),
        }
    )
