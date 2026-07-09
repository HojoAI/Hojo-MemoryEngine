"""User memory list/detail backed by memory_data (same granularity as list-all)."""

from datetime import datetime

from memory_engine.core.context import RequestContext
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.integrations import mongo_store
from memory_engine.schemas.user_memory_item import (
    UserMemoryItemDetailOut,
    UserMemoryItemListPage,
    build_item_detail_out,
    build_item_out,
)
from sqlalchemy.ext.asyncio import AsyncSession

_PENDING_STATUS = frozenset({"pending", "pending_confirmation", "待确认"})


def _normalize_time(value: str | None, *, end_of_day: bool = False) -> str | None:
    """Accept ISO datetime or YYYY-MM-DD for range filters."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        suffix = "T23:59:59.999999+00:00" if end_of_day else "T00:00:00+00:00"
        try:
            datetime.fromisoformat(raw)
        except ValueError:
            return None
        return f"{raw}{suffix}"
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return raw


def _status_is_empty(status: str | None) -> bool:
    if not status or not status.strip():
        return False
    return status.strip().lower() in _PENDING_STATUS


async def list_user_memory_items_page(
    session: AsyncSession | None,
    ctx: RequestContext,
    user_id: str,
    *,
    page_id: int = 1,
    page_size: int = 10,
    dimension: str | None = None,
    source: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    sort_field: str = "updated_at",
    sort_order: str = "desc",
) -> UserMemoryItemListPage:
    """Paginated list from memory_data (one row per memory_field_name)."""
    _ = session
    page_id = max(page_id, 1)
    page_size = min(max(page_size, 1), 200)
    offset = (page_id - 1) * page_size
    sort_desc = sort_order.lower() != "asc"
    normalized_start = _normalize_time(start_time, end_of_day=False)
    normalized_end = _normalize_time(end_time, end_of_day=True)

    if _status_is_empty(status):
        return UserMemoryItemListPage(
            page_id=page_id,
            page_size=page_size,
            total_count=0,
            page_content=[],
        )

    total = await mongo_store.count_memory_data_for_user_filtered(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        dimension=dimension,
        source=source,
        keyword=keyword,
        start_time=normalized_start,
        end_time=normalized_end,
    )
    docs = await mongo_store.list_memory_data_for_user_filtered(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        dimension=dimension,
        source=source,
        keyword=keyword,
        start_time=normalized_start,
        end_time=normalized_end,
        offset=offset,
        limit=page_size,
        sort_field=sort_field,
        sort_desc=sort_desc,
    )
    return UserMemoryItemListPage(
        page_id=page_id,
        page_size=page_size,
        total_count=total,
        page_content=[build_item_out(doc) for doc in docs],
    )


async def get_user_memory_item_detail(
    session: AsyncSession | None,
    ctx: RequestContext,
    user_id: str,
    item_id: str,
) -> UserMemoryItemDetailOut:
    """Return one memory_data row as detail (item_id = memory_data._id)."""
    _ = session
    normalized_id = (item_id or "").strip()
    if not normalized_id:
        raise UserApiError("ILLEGAL_ARGUMENT", "itemId 不能为空")

    doc = await mongo_store.get_memory_data_by_id(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        normalized_id,
    )
    if doc is None:
        raise UserApiError("NOT_FOUND", "记忆不存在")
    return build_item_detail_out(doc)
