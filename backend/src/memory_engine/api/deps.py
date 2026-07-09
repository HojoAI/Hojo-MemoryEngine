"""FastAPI dependencies."""

import secrets
from dataclasses import dataclass
from datetime import datetime

import bcrypt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.core.permissions import permission_granted
from memory_engine.db.session import get_db
from memory_engine.models.auth import ApiKey
from memory_engine.services.user_token_auth import validate_user_token
from memory_engine.services.end_user_memory import resolve_end_user_tenant_org

def _verify_api_key(raw_key: str, key_hash: str) -> bool:
    """Verify raw API key against stored bcrypt hash."""
    try:
        return bcrypt.checkpw(raw_key.encode("utf-8"), key_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def get_request_context(
    request: Request,
    session: AsyncSession = Depends(get_db),
    x_tenant_id: int | None = Header(None, alias="X-Tenant-Id"),
    x_org_id: int | None = Header(None, alias="X-Org-Id"),
    x_user_id: int | None = Header(None, alias="X-User-Id"),
    authorization: str | None = Header(None),
) -> RequestContext:
    """Resolve tenant scope; API key auth when APP_DISABLE_AUTH is false."""
    settings = get_settings()

    if settings.app_disable_auth:
        if x_tenant_id is None:
            raise ForbiddenError("X-Tenant-Id required when auth is disabled")
        return RequestContext(
            tenant_id=x_tenant_id,
            org_id=x_org_id or 0,
            user_id=x_user_id,
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise ForbiddenError("Missing Bearer API key")

    raw_key = authorization.split(" ", 1)[1].strip()
    if len(raw_key) < 8:
        raise ForbiddenError("Invalid API key")
    prefix = raw_key[:16] if len(raw_key) >= 16 else raw_key[:8]
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.deleted == 0)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ForbiddenError("Invalid API key")
    if row.revoked_at is not None:
        raise ForbiddenError("API key revoked")
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise ForbiddenError("API key expired")
    if not _verify_api_key(raw_key, row.key_hash):
        raise ForbiddenError("Invalid API key")

    if x_tenant_id is not None and x_tenant_id != row.tenant_id:
        raise ForbiddenError("X-Tenant-Id does not match API key tenant")
    if x_org_id is not None and x_org_id != row.org_id:
        raise ForbiddenError("X-Org-Id does not match API key organization")

    ctx = RequestContext(
        tenant_id=row.tenant_id,
        org_id=row.org_id,
        user_id=row.user_id,
        api_key_id=row.id,
    )
    if row.permissions_json:
        perms = row.permissions_json.get("allow", [])
        if isinstance(perms, list):
            ctx.permissions = {str(p) for p in perms}
    return ctx


async def require_service_bearer(
    x_tenant_id: int | None = Header(None, alias="X-Tenant-Id"),
    x_org_id: int | None = Header(None, alias="X-Org-Id"),
    authorization: str | None = Header(None),
) -> RequestContext:
    """Service Bearer auth for /data/user/* (not API key)."""
    settings = get_settings()
    expected = settings.service_bearer_token.strip()
    if not expected:
        raise ForbiddenError(
            "Service bearer auth disabled (set MEMORY_ENGINE_SERVICE_BEARER_TOKEN)"
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ForbiddenError("Missing Bearer service token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise ForbiddenError("Invalid service bearer token")
    if x_tenant_id is None:
        raise ForbiddenError("X-Tenant-Id required")
    return RequestContext(
        tenant_id=x_tenant_id,
        org_id=x_org_id or 0,
        user_id=None,
    )


def require_permission(permission: str):
    """Dependency factory for permission check."""

    async def _checker(ctx: RequestContext = Depends(get_request_context)) -> RequestContext:
        settings = get_settings()
        if settings.app_disable_auth:
            return ctx
        if permission_granted(ctx.permissions, permission):
            return ctx
        raise ForbiddenError(f"Missing permission: {permission}")

    return _checker


@dataclass
class EndUserContext:
    """Authenticated end-user scope for ``/data/user/*``."""

    platform_user_id: str
    tenant_id: int
    org_id: int

    def to_request_context(self) -> RequestContext:
        return RequestContext(tenant_id=self.tenant_id, org_id=self.org_id, user_id=None)


async def require_end_user(
    session: AsyncSession = Depends(get_db),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
    x_user_token: str | None = Header(None, alias="X-User-Token"),
    x_tenant_id: int | None = Header(None, alias="X-Tenant-Id"),
    x_org_id: int | None = Header(None, alias="X-Org-Id"),
) -> EndUserContext:
    """End-user login: ``X-User-Id`` + ``X-User-Token``."""
    if not x_user_id or not x_user_id.strip():
        raise UserApiError("ILLEGAL_ARGUMENT", "缺少请求头 X-User-Id")
    if not x_user_token or not x_user_token.strip():
        raise UserApiError("ILLEGAL_ARGUMENT", "缺少请求头 X-User-Token")

    platform_user_id = x_user_id.strip()
    token = x_user_token.strip()
    await validate_user_token(platform_user_id, token)
    tenant_id, org_id = await resolve_end_user_tenant_org(
        session, platform_user_id, x_tenant_id, x_org_id
    )
    return EndUserContext(
        platform_user_id=platform_user_id,
        tenant_id=tenant_id,
        org_id=org_id,
    )
