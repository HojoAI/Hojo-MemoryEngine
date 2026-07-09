"""Admin bootstrap: tenant / org / user / api_key."""

from __future__ import annotations

import secrets

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.exceptions import ConflictError
from memory_engine.models.auth import ApiKey
from memory_engine.models.tenant import AppUser, Organization, Tenant
from memory_engine.schemas.admin import TenantBootstrapRequest, TenantBootstrapResponse

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def bootstrap_tenant(
    session: AsyncSession, body: TenantBootstrapRequest
) -> TenantBootstrapResponse:
    """Create tenant hierarchy and return a new API key (plaintext once)."""
    existing = await session.execute(
        select(Tenant).where(Tenant.tenant_code == body.tenant_code, Tenant.deleted == 0)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"tenant_code '{body.tenant_code}' already exists")

    tenant = Tenant(
        tenant_code=body.tenant_code,
        name=body.tenant_name,
        status="active",
    )
    session.add(tenant)
    await session.flush()

    org = Organization(
        tenant_id=tenant.id,
        org_code=body.org_code,
        name=body.org_name,
        status="active",
    )
    session.add(org)
    await session.flush()

    user = AppUser(
        tenant_id=tenant.id,
        org_id=org.id,
        email=body.email,
        display_name=body.display_name or body.email,
        supabase_user_id=body.supabase_user_id,
        status="active",
    )
    session.add(user)
    await session.flush()

    raw_key = "mos_" + secrets.token_urlsafe(24)[:20]
    key_prefix = raw_key[:16]
    api_key = ApiKey(
        tenant_id=tenant.id,
        org_id=org.id,
        user_id=user.id,
        key_prefix=key_prefix,
        key_hash=_pwd.hash(raw_key),
        name=body.api_key_name,
        permissions_json={
            "allow": [
                "schema:*",
                "data:*",
                "billing:*",
                "governance:*",
                "admin:bootstrap",
            ]
        },
    )
    session.add(api_key)
    await session.commit()

    return TenantBootstrapResponse(
        tenant_id=tenant.id,
        org_id=org.id,
        user_id=user.id,
        api_key_id=api_key.id,
        api_key=raw_key,
        key_prefix=key_prefix,
    )
