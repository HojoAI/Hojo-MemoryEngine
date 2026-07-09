"""Internal endpoints for APISIX gateway auth plugin."""

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import _verify_api_key
from memory_engine.db.session import get_db
from memory_engine.models.auth import ApiKey
from memory_engine.schemas.common import ApiResponse

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/auth/validate", response_model=ApiResponse)
async def validate_api_key_for_gateway(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """APISIX forward-auth: validate Bearer API key exists and is active."""
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="missing bearer token")
    raw_key = authorization.split(" ", 1)[1].strip()
    prefix = raw_key[:16] if len(raw_key) >= 16 else raw_key[:8]
    row = (
        await session.execute(
            select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.deleted == 0)
        )
    ).scalar_one_or_none()
    if not row or row.revoked_at is not None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="invalid key")
    if not _verify_api_key(raw_key, row.key_hash):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="invalid key")
    return ApiResponse(
        data={
            "tenant_id": row.tenant_id,
            "org_id": row.org_id,
            "user_id": row.user_id,
            "api_key_id": row.id,
        }
    )
