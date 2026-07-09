"""LLM provider management API."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.models.misc import LlmProvider
from memory_engine.schemas.common import ApiResponse

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post("/providers", response_model=ApiResponse)
async def create_provider(
    provider_code: str,
    provider_type: str,
    base_url: str,
    default_model: str,
    api_key_secret_ref: int | None = None,
    extra_config_json: dict | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:manage")),
) -> ApiResponse:
    row = LlmProvider(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        provider_code=provider_code,
        provider_type=provider_type,
        base_url=base_url,
        default_model=default_model,
        api_key_secret_ref=api_key_secret_ref,
        extra_config_json=extra_config_json,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiResponse(data={"id": row.id, "provider_code": row.provider_code})


@router.get("/providers", response_model=ApiResponse)
async def list_providers(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("billing:read")),
) -> ApiResponse:
    rows = (
        await session.execute(
            select(LlmProvider).where(
                LlmProvider.tenant_id == ctx.tenant_id,
                LlmProvider.deleted == 0,
            )
        )
    ).scalars().all()
    return ApiResponse(
        data=[
            {
                "id": r.id,
                "provider_code": r.provider_code,
                "base_url": r.base_url,
                "default_model": r.default_model,
                "status": r.status,
            }
            for r in rows
        ]
    )
