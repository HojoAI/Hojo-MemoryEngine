"""Memory data API routes (/data/*)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import EndUserContext, require_end_user, require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.schemas.common import ApiResponse, SearchMode
from memory_engine.schemas.user_api_response import UserApiResponse, user_api_ok
from memory_engine.schemas.memory_field import (
    DataCallRequest,
    DataRetrieveRequest,
    MemoryDataCreate,
    MemoryDataUpdate,
    UserMemoryExportEmailRequest,
)
from memory_engine.services import memory_data as data_service
from memory_engine.services import memory_retrieve as retrieve_service
from memory_engine.services import user_memory_list as user_list_service
from memory_engine.services.end_user_memory import resolve_end_user_memory_user_id
from memory_engine.services.memory_export_email import export_memory_data_to_email
from memory_engine.services.memory_user import resolve_memory_user_id
from memory_engine.services.workflow_launch import launch_data_write

router = APIRouter(prefix="/data", tags=["data"]) # 定义路由URL


@router.post("/create", response_model=ApiResponse)
async def data_create(
    body: MemoryDataCreate,     # 请求体，FastAPI自动把JSON转MemoryDataCreate对象
    use_temporal: bool = False, # 控制用不用工作流
    wait: bool = False,         # 控制异步执行完后是否传回运行结果
    session: AsyncSession = Depends(get_db), # 异步MySQL 会话
    ctx: RequestContext = Depends(require_permission("data:create")), # FastAPI依赖闭包，校验当前用户是否持有权限
) -> ApiResponse:
    if use_temporal:
        data = await launch_data_write(ctx, body, wait=wait)
        return ApiResponse(data=data.get("result", data) if isinstance(data, dict) else data)
    out = await data_service.create(session, ctx, body)
    return ApiResponse(data=out)


@router.post("/update", response_model=ApiResponse)
async def data_update(
    body: MemoryDataUpdate,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:update")),
) -> ApiResponse:
    out = await data_service.update(session, ctx, body)
    return ApiResponse(data=out)


@router.post("/delete", response_model=ApiResponse)
async def data_delete(
    user_id: str,
    memory_field_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:delete")),
) -> ApiResponse:
    await data_service.delete_soft(session, ctx, user_id, memory_field_name)
    return ApiResponse(message="deleted")


@router.get("/get", response_model=ApiResponse)
async def data_get(
    user_id: str,
    memory_field_name: str,
    mode: SearchMode = SearchMode.EXACT,
    query: str = "",
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    out = await data_service.get(
        session, ctx, user_id, memory_field_name, mode=mode, query=query
    )
    return ApiResponse(data=out)


@router.post("/retrieve", response_model=ApiResponse)
async def data_retrieve(
    body: DataRetrieveRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    """Explicit or implicit retrieve (EXACT / REGEX / SEMANTIC / LLM)."""
    out = await retrieve_service.retrieve(session, ctx, body)
    return ApiResponse(data=out)


@router.post("/call", response_model=ApiResponse)
async def data_call(
    body: DataCallRequest,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    """Fill slot with memory data and optionally invoke LLM."""
    out = await retrieve_service.call_memory(session, ctx, body)
    return ApiResponse(data=out)


@router.get("/list", response_model=ApiResponse)
async def data_list(
    user_id: str | None = None,
    memory_field_name: str | None = None,
    scope: Literal["partition", "tenant"] = "partition",
    offset: int = 0,
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("data:read")),
) -> ApiResponse:
    """List memory data (debug / dashboard).

    - ``scope=tenant``: all active rows under ``tenant_id`` + ``org_id`` (optional ``user_id`` substring filter).
    - ``scope=partition`` (default): one partition; when ``user_id`` is omitted, uses API key ``key_prefix``.
    """
    cap = min(limit, 200)
    if scope == "tenant":
        page = await data_service.list_for_tenant_page(
            session,
            ctx,
            memory_field_name=memory_field_name,
            user_id=user_id,
            offset=offset,
            limit=cap,
        )
        return ApiResponse(data=page)
    uid = await resolve_memory_user_id(session, ctx, user_id)
    page = await data_service.list_for_user_page(
        session,
        ctx,
        uid,
        memory_field_name=memory_field_name,
        offset=offset,
        limit=cap,
    )
    return ApiResponse(data=page)


@router.get("/user/has-data", response_model=UserApiResponse)
async def data_user_has_data(
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """Return whether the authenticated end-user has any active memory data."""
    ctx = h5.to_request_context()
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    out = await data_service.user_has_memory_data(session, ctx, memory_user_id)
    return user_api_ok(out.model_dump())


@router.get("/user/list", response_model=UserApiResponse)
async def data_user_list(
    page_id: int = Query(1, alias="pageId", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=200),
    dimension: str | None = None,
    source: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    start_time: str | None = Query(None, alias="startTime"),
    end_time: str | None = Query(None, alias="endTime"),
    sort_field: str = Query("updated_at", alias="sortField"),
    sort_order: str = Query("desc", alias="sortOrder"),
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """List personal memory rows (one memory_data doc per item, same scope as ``list-all``)."""
    ctx = h5.to_request_context()
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    page = await user_list_service.list_user_memory_items_page(
        session,
        ctx,
        memory_user_id,
        page_id=page_id,
        page_size=page_size,
        dimension=dimension,
        source=source,
        status=status,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
        sort_field=sort_field,
        sort_order=sort_order,
    )
    return user_api_ok(page.model_dump(by_alias=True))


@router.get("/user/detail", response_model=UserApiResponse)
async def data_user_detail(
    item_id: str = Query(..., alias="itemId", min_length=1),
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """Get one memory_data row detail (``itemId`` = memory_data ``_id``)."""
    ctx = h5.to_request_context()   # 外部H5平台的用户身份 → 内部服务层通用的请求上下文
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    detail = await user_list_service.get_user_memory_item_detail(
        session,
        ctx,
        memory_user_id,
        item_id,
    )
    return user_api_ok(detail.model_dump(by_alias=True, exclude_none=True))


@router.get("/user/list-all", response_model=UserApiResponse)
async def data_user_list_all(
    offset: int = 0,
    limit: int = 200,
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """List all memory **data** for the authenticated end-user (paginated)."""
    ctx = h5.to_request_context()
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    out = await data_service.list_all_for_user(
        session,
        ctx,
        memory_user_id,
        offset=offset,
        limit=min(limit, 1000),
    )
    payload = out.model_dump() if hasattr(out, "model_dump") else out
    return user_api_ok(payload)


@router.post("/user/delete-all", response_model=UserApiResponse)
async def data_user_delete_all(
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """Soft-delete all memory **data** for the authenticated end-user."""
    ctx = h5.to_request_context()
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    out = await data_service.delete_all_for_user(session, ctx, memory_user_id)
    payload = out.model_dump() if hasattr(out, "model_dump") else out
    return user_api_ok(payload, res_message="已清空记忆数据")


@router.post("/user/export-email", response_model=UserApiResponse)
async def data_user_export_email(
    body: UserMemoryExportEmailRequest,
    session: AsyncSession = Depends(get_db),
    h5: EndUserContext = Depends(require_end_user),
) -> UserApiResponse:
    """Email memory **data** for the authenticated end-user (same scope as ``list-all``)."""
    ctx = h5.to_request_context()
    memory_user_id = await resolve_end_user_memory_user_id(
        session, h5.platform_user_id, h5.tenant_id, h5.org_id
    )
    out = await export_memory_data_to_email(
        session,
        ctx,
        memory_user_id,
        body.email,
        offset=body.offset,
        limit=body.limit,
    )
    return user_api_ok(out.model_dump(), res_message="记忆数据已发送至邮箱")
