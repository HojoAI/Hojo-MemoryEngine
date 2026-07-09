"""Onboarding: Supabase-linked users, API key issuance, profile."""

from __future__ import annotations

import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from memory_engine.models.auth import ApiKey
from memory_engine.models.tenant import AppUser, Organization, Tenant
from memory_engine.schemas.admin import TenantBootstrapRequest, TenantBootstrapResponse
from memory_engine.schemas.onboarding import (
    ApiKeyIssueResponse,
    ApiKeySummary,
    OnboardingProfileResponse,
)
from memory_engine.services import admin_service

_DEFAULT_PERMISSIONS = {
    "allow": [
        "schema:*",
        "data:*",
        "billing:read",
        "billing:write",
        "governance:*",
        "user:read",
        "user:manage",
        "api_key:manage",
    ]
}


def _generate_api_key_material() -> tuple[str, str]:
    raw_key = "mos_" + secrets.token_urlsafe(24)[:20]
    return raw_key, raw_key[:16]


def _hash_key(raw_key: str) -> str:
    return bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def _issue_api_key(
    session: AsyncSession,
    *,
    tenant_id: int,
    org_id: int,
    user_id: int,
    name: str,
    permissions: dict | None = None,
) -> ApiKeyIssueResponse:
    raw_key, key_prefix = _generate_api_key_material()
    for _ in range(5):
        existing = (
            await session.execute(
                select(ApiKey.id).where(ApiKey.key_prefix == key_prefix, ApiKey.deleted == 0)
            )
        ).scalar_one_or_none()
        if not existing:
            break
        raw_key, key_prefix = _generate_api_key_material()
    else:
        raise ConflictError("failed to generate unique api key prefix")

    row = ApiKey(
        tenant_id=tenant_id,
        org_id=org_id,
        user_id=user_id,
        key_prefix=key_prefix,
        key_hash=_hash_key(raw_key),
        name=name,
        permissions_json=permissions or _DEFAULT_PERMISSIONS,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiKeyIssueResponse(
        tenant_id=tenant_id,
        org_id=org_id,
        user_id=user_id,
        api_key_id=row.id,
        api_key=raw_key,
        key_prefix=key_prefix,
    )


def _api_key_summary(row: ApiKey) -> ApiKeySummary:
    return ApiKeySummary(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        tenant_id=row.tenant_id,
        org_id=row.org_id,
        user_id=row.user_id,
        revoked_at=row.revoked_at,
        expires_at=row.expires_at,
        create_time=row.create_time,
    )


async def get_profile_by_supabase(
    session: AsyncSession, supabase_user_id: str
) -> OnboardingProfileResponse:
    """Load user profile and API key prefixes for a Supabase user."""
    user = (
        await session.execute(
            select(AppUser).where(
                AppUser.supabase_user_id == supabase_user_id,
                AppUser.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not user:
        raise NotFoundError("Memory Engine user not linked; apply for an API key first")

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == user.tenant_id, Tenant.deleted == 0))
    ).scalar_one_or_none()
    org = (
        await session.execute(
            select(Organization).where(
                Organization.id == user.org_id,
                Organization.tenant_id == user.tenant_id,
                Organization.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    keys = (
        (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.user_id == user.id,
                    ApiKey.tenant_id == user.tenant_id,
                    ApiKey.deleted == 0,
                )
            )
        )
        .scalars()
        .all()
    )
    return OnboardingProfileResponse(
        tenant_id=user.tenant_id,
        org_id=user.org_id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_code=tenant.tenant_code if tenant else None,
        org_code=org.org_code if org else None,
        api_keys=[_api_key_summary(k) for k in keys],
    )


async def apply_api_key_for_supabase(
    session: AsyncSession,
    *,
    supabase_user_id: str,
    email: str,
    display_name: str | None,
    key_name: str,
) -> ApiKeyIssueResponse:
    """Link Supabase user to MemoryEngine (create tenant if needed) and issue API key."""
    user = (
        await session.execute(
            select(AppUser).where(
                AppUser.supabase_user_id == supabase_user_id,
                AppUser.deleted == 0,
            )
        )
    ).scalar_one_or_none()

    if not user:
        by_email = (
            await session.execute(
                select(AppUser).where(AppUser.email == email, AppUser.deleted == 0)
            )
        ).scalar_one_or_none()
        if by_email:
            if (
                by_email.supabase_user_id
                and by_email.supabase_user_id != supabase_user_id
            ):
                raise ConflictError("email already linked to another Supabase account")
            by_email.supabase_user_id = supabase_user_id
            if display_name:
                by_email.display_name = display_name
            await session.commit()
            await session.refresh(by_email)
            user = by_email
        else:
            slug = supabase_user_id.replace("-", "")[:12]
            bootstrap = TenantBootstrapRequest(
                tenant_code=f"sb-{slug}",
                tenant_name=f"{display_name or email} Workspace",
                org_code="default",
                org_name="Default Organization",
                email=email,
                display_name=display_name or email,
                api_key_name=key_name,
                supabase_user_id=supabase_user_id,
            )
            created: TenantBootstrapResponse = await admin_service.bootstrap_tenant(
                session, bootstrap
            )
            return ApiKeyIssueResponse(
                tenant_id=created.tenant_id,
                org_id=created.org_id,
                user_id=created.user_id,
                api_key_id=created.api_key_id,
                api_key=created.api_key,
                key_prefix=created.key_prefix,
            )

    return await _issue_api_key(
        session,
        tenant_id=user.tenant_id,
        org_id=user.org_id,
        user_id=user.id,
        name=key_name,
    )


async def create_api_key_for_context(
    session: AsyncSession,
    ctx: RequestContext,
    name: str,
) -> ApiKeyIssueResponse:
    """Issue another API key for the authenticated user."""
    if ctx.user_id is None:
        raise ForbiddenError("user context required")
    return await _issue_api_key(
        session,
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        name=name,
    )


async def list_api_keys_for_context(
    session: AsyncSession, ctx: RequestContext
) -> list[ApiKeySummary]:
    """List API keys visible to the current user."""
    q = select(ApiKey).where(
        ApiKey.tenant_id == ctx.tenant_id,
        ApiKey.deleted == 0,
    )
    if ctx.user_id is not None:
        q = q.where(ApiKey.user_id == ctx.user_id)
    rows = (await session.execute(q)).scalars().all()
    return [_api_key_summary(r) for r in rows]
