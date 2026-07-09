"""Dashboard user management API."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError
from memory_engine.db.session import get_db
from memory_engine.models.tenant import AppUser
from memory_engine.schemas.common import ApiResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/list", response_model=ApiResponse)
async def list_users(
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("user:read")),
) -> ApiResponse:
    rows = (
        await session.execute(
            select(AppUser)
            .where(AppUser.tenant_id == ctx.tenant_id, AppUser.deleted == 0)
            .limit(limit)
        )
    ).scalars().all()
    return ApiResponse(
        data=[
            {
                "id": r.id,
                "email": r.email,
                "display_name": r.display_name,
                "status": r.status,
                "supabase_user_id": r.supabase_user_id,
            }
            for r in rows
        ]
    )


@router.post("/create", response_model=ApiResponse)
async def create_user(
    email: str,
    display_name: str | None = None,
    supabase_user_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("user:manage")),
) -> ApiResponse:
    row = AppUser(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        email=email,
        display_name=display_name,
        supabase_user_id=supabase_user_id,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiResponse(data={"id": row.id, "email": row.email})


@router.post("/update", response_model=ApiResponse)
async def update_user(
    user_id: int,
    display_name: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("user:manage")),
) -> ApiResponse:
    row = (
        await session.execute(
            select(AppUser).where(
                AppUser.id == user_id,
                AppUser.tenant_id == ctx.tenant_id,
                AppUser.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("user not found")
    if display_name is not None:
        row.display_name = display_name
    if status is not None:
        row.status = status
    row.updated_by = ctx.user_id
    await session.commit()
    return ApiResponse(data={"id": row.id})


@router.post("/delete", response_model=ApiResponse)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("user:manage")),
) -> ApiResponse:
    row = (
        await session.execute(
            select(AppUser).where(
                AppUser.id == user_id,
                AppUser.tenant_id == ctx.tenant_id,
                AppUser.deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundError("user not found")
    row.deleted = 1
    row.updated_by = ctx.user_id
    await session.commit()
    return ApiResponse(message="deleted")
