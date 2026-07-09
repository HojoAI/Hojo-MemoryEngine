"""Memory data service (Mongo + Qdrant)."""

from typing import Any

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError, ValidationError
from memory_engine.config import get_settings
from memory_engine.constants.user_memory_item import (
    normalize_memory_source,
    resolve_write_memory_source,
)
from memory_engine.integrations import mongo_store, qdrant_index_queue, qdrant_store
from memory_engine.schemas.common import SearchMode
from memory_engine.schemas.memory_field import (
    MemoryDataCreate,
    MemoryDataListPage,
    MemoryDataOut,
    MemoryDataUpdate,
    UserMemoryDataDeleteResult,
    UserMemoryDataExistsResult,
    UserMemoryDataListResult,
)
from memory_engine.services import memory_field as mf_service
from memory_engine.services import memory_merge
from memory_engine.services import memory_parse
from memory_engine.services import rules as rule_service
from memory_engine.services import data_search
from sqlalchemy.ext.asyncio import AsyncSession


async def _get_field(session: AsyncSession, ctx: RequestContext, name: str):
    field = await mf_service.get_active_by_name(session, ctx, name)
    if not field:
        raise NotFoundError(f"memory_field '{name}' not found")
    return field


def _match_method(field, write_rule: str | None) -> str:
    if write_rule:
        return write_rule.upper()
    return field.match_method


DEFAULT_MERGE_RULE_NAME = "merge_default"


async def _resolve_merge_rule_name(
    session: AsyncSession,
    ctx: RequestContext,
    memory_field_name: str,
    merge_rule_name: str | None,
) -> str | None:
    """Pick merge rule: explicit name, else active ``merge_default``, else None."""
    if merge_rule_name:
        return merge_rule_name
    row = await rule_service.get_active_merge(
        session, ctx, memory_field_name, DEFAULT_MERGE_RULE_NAME
    )
    return DEFAULT_MERGE_RULE_NAME if row else None


async def _apply_merge_strategy(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_id: str,
    memory_field_name: str,
    value: Any,
    match_method: str,
    merge_rule_name: str | None,
) -> tuple[Any, str]:
    """``MERGE`` writes use merge_rule + LLM to fuse old/new; result stored via OVERWRITE."""
    if match_method != "MERGE":
        return value, match_method

    existing = await mongo_store.get_memory_data(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name
    )
    if not existing or existing.get("deleted") == 1:
        return value, match_method

    resolved_rule = await _resolve_merge_rule_name(
        session, ctx, memory_field_name, merge_rule_name
    )
    if not resolved_rule:
        raise ValidationError(
            f"memory_field '{memory_field_name}' uses match_method MERGE but no merge_rule "
            f"is registered (register via POST /schema/merge/create or Schema.getOrCreate merge_rule)"
        )
    merged = await memory_merge.merge_with_rule(
        session,
        ctx,
        memory_field_name=memory_field_name,
        old_value=existing.get("value"),
        new_value=value,
        rule_name=resolved_rule,
    )
    return merged, "OVERWRITE"


async def _index_vector_async(
    field,
    ctx: RequestContext,
    user_id: str,
    memory_field_name: str,
    doc_id: str,
    value,
    *,
    action: str = "upsert",
) -> None:
    if action == "upsert" and memory_parse.parse_result_is_empty(value):
        return
    if field.storage_type not in ("VECTOR", "KV_AND_VECTOR"):
        return
    settings = get_settings()
    if settings.qdrant_async_index:
        qdrant_index_queue.enqueue_vector_index(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            user_id=user_id,
            memory_field_name=memory_field_name,
            doc_id=doc_id,
            text=str(value),
            action=action,
        )
    else:
        await qdrant_index_queue.enqueue_vector_index_blocking(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            user_id=user_id,
            memory_field_name=memory_field_name,
            doc_id=doc_id,
            text=str(value),
            action=action,
        )


async def _resolve_value(
    session: AsyncSession, ctx: RequestContext, body: MemoryDataCreate
):
    if body.value is not None:
        return await memory_parse._translate_value(body.value, body.language, session, ctx)
    raw = body.query or ""
    return await memory_parse.parse_with_rule(
        session,
        ctx,
        memory_field_name=body.memory_field_name,
        rule_name=body.parse_rule_name,
        raw_query=raw,
        extra=body.extra,
        output_language=body.language,
    )



def _out_without_write(body: MemoryDataCreate, existing: dict | None) -> MemoryDataOut:
    """Response when parse yielded nothing — no Mongo/Qdrant side effects."""
    if existing and existing.get("deleted") == 0:
        return MemoryDataOut(
            user_id=body.user_id,
            memory_field_name=body.memory_field_name,
            value=existing.get("value"),
        )
    return MemoryDataOut(
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=None,
    )


async def create(session: AsyncSession, ctx: RequestContext, body: MemoryDataCreate) -> MemoryDataOut:
    field = await _get_field(session, ctx, body.memory_field_name) # 查数据库确认memory_field_name是否存在并处于激活状态，拿到的是该字段的元信息（类型、匹配方式、存储类型等），后续写入全靠它。
    match_method = _match_method(field, body.write_rule) # 决定本次写入用哪种冲突策略：请求里显式传了 write_rule 就用它，没传则用该字段默认的 match_method（OVERWRITE/APPEND/MERGE）
    try:
        memory_source = resolve_write_memory_source(body.source, body.parse_rule_name)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    value = await _resolve_value(session, ctx, body) # 如果请求里直接给了value就直接用；否则拿query调LLM解析规则，让LLM提取出结构化记忆
    existing = await mongo_store.get_memory_data(
        ctx.tenant_id, ctx.org_id, body.user_id, body.memory_field_name
    ) # 查MongoDB里该用户在这个记忆字段下是否已有数据，用于判断本次是新增还是冲突合并
    if memory_parse.parse_result_is_empty(value):
        return _out_without_write(body, existing) # LLM 解析出的结果为空（无意义/无需存储），跳过写库直接返回——已有数据就回原值，没有就回空

    if existing and existing.get("deleted") == 0: # 有未删除数据 → 更新路径：
        # _apply_merge_strategy 根据策略（覆盖/追加/LLM融合）把新旧值合并
        value, effective_match = await _apply_merge_strategy(
            session,
            ctx,
            user_id=body.user_id,
            memory_field_name=body.memory_field_name,
            value=value,
            match_method=match_method,
            merge_rule_name=body.merge_rule_name,
        )
        # 合并后为空 → 不写，回原值
        if memory_parse.parse_result_is_empty(value):
            return _out_without_write(body, existing)
        # 合并后有内容→调update覆写Mongo+Qdrant
        return await update(
            session,
            ctx,
            MemoryDataUpdate(
                user_id=body.user_id,
                memory_field_name=body.memory_field_name,
                value=value,
                write_rule="OVERWRITE" if effective_match == "OVERWRITE" else body.write_rule,
                merge_rule_name=body.merge_rule_name,
                source=memory_source,
            ),
        )

    # 新增路径：之前没数据，直接往 MongoDB 写入一条新记忆文档
    doc = await mongo_store.upsert_memory_data(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.memory_field_name,
        value,
        match_method=match_method,
        source=memory_source,
    )
    # 判断是否需要向量写入，然后决定走异步队列还是同步阻塞方式写入 Qdrant
    await _index_vector_async(
        field, ctx, body.user_id, body.memory_field_name, doc["_id"], doc["value"]
    )
    # 新增记忆的结果（用户ID、字段名、写入后的值）封装成 API 响应对象返回
    return MemoryDataOut(
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
    )


async def update(session: AsyncSession, ctx: RequestContext, body: MemoryDataUpdate) -> MemoryDataOut:
    field = await _get_field(session, ctx, body.memory_field_name)
    try:
        memory_source = normalize_memory_source(body.source)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if memory_parse.parse_result_is_empty(body.value):
        existing = await mongo_store.get_memory_data(
            ctx.tenant_id, ctx.org_id, body.user_id, body.memory_field_name
        )
        if existing and existing.get("deleted") == 0:
            return MemoryDataOut(
                user_id=body.user_id,
                memory_field_name=body.memory_field_name,
                value=existing.get("value"),
            )
        raise NotFoundError("memory data not found")
    match_method = _match_method(field, body.write_rule)
    value, effective_match = await _apply_merge_strategy(
        session,
        ctx,
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=body.value,
        match_method=match_method,
        merge_rule_name=body.merge_rule_name,
    )
    doc = await mongo_store.upsert_memory_data(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.memory_field_name,
        value,
        match_method=effective_match,
        source=memory_source,
    )
    await _index_vector_async(
        field, ctx, body.user_id, body.memory_field_name, doc["_id"], doc["value"]
    )
    return MemoryDataOut(
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
    )


async def delete_soft(
    session: AsyncSession, ctx: RequestContext, user_id: str, memory_field_name: str
) -> None:
    field = await _get_field(session, ctx, memory_field_name)
    ok = await mongo_store.soft_delete_memory_data(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name
    )
    if not ok:
        raise NotFoundError("memory data not found")
    doc_id = mongo_store._doc_id(ctx.tenant_id, ctx.org_id, user_id, memory_field_name)
    await _index_vector_async(
        field, ctx, user_id, memory_field_name, doc_id, "", action="delete"
    )


async def get(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str,
    memory_field_name: str,
    *,
    mode: SearchMode = SearchMode.EXACT,
    query: str = "",
) -> MemoryDataOut:
    await _get_field(session, ctx, memory_field_name)
    if mode == SearchMode.EXACT and not query:
        doc = await mongo_store.get_memory_data(
            ctx.tenant_id, ctx.org_id, user_id, memory_field_name
        )
        if not doc:
            raise NotFoundError("memory data not found")
        return MemoryDataOut(
            user_id=user_id,
            memory_field_name=memory_field_name,
            value=doc.get("value"),
            deleted=doc.get("deleted", 0),
        )
    out = await data_search.search_memory_data(
        ctx, user_id, memory_field_name, query, mode
    )
    if not out:
        raise NotFoundError("memory data not found")
    return out


async def list_for_user_page(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str,
    *,
    memory_field_name: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> MemoryDataListPage:
    if memory_field_name:
        await _get_field(session, ctx, memory_field_name)
    total = await mongo_store.count_memory_data_for_user(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        memory_field_name=memory_field_name,
    )
    docs = await mongo_store.list_memory_data_for_user(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        memory_field_name=memory_field_name,
        offset=offset,
        limit=limit,
    )
    items = [
        MemoryDataOut(
            user_id=d["user_id"],
            memory_field_name=d["memory_field_name"],
            value=d.get("value"),
            deleted=d.get("deleted", 0),
        )
        for d in docs
    ]
    return MemoryDataListPage(items=items, total=total)


async def list_for_tenant_page(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    memory_field_name: str | None = None,
    user_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> MemoryDataListPage:
    """List active memory data for all partitions under tenant/org."""
    if memory_field_name:
        await _get_field(session, ctx, memory_field_name)
    total = await mongo_store.count_memory_data_for_tenant(
        ctx.tenant_id,
        ctx.org_id,
        memory_field_name=memory_field_name,
        user_id=user_id,
    )
    docs = await mongo_store.list_memory_data_for_tenant(
        ctx.tenant_id,
        ctx.org_id,
        memory_field_name=memory_field_name,
        user_id=user_id,
        offset=offset,
        limit=limit,
    )
    items = [
        MemoryDataOut(
            user_id=d["user_id"],
            memory_field_name=d["memory_field_name"],
            value=d.get("value"),
            deleted=d.get("deleted", 0),
        )
        for d in docs
    ]
    return MemoryDataListPage(items=items, total=total)


async def list_all_for_user(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
    *,
    offset: int = 0,
    limit: int = 200,
) -> UserMemoryDataListResult:
    """List all active memory data for a Mongo/Qdrant partition (service API)."""
    page = await list_for_user_page(
        session,
        ctx,
        memory_user_id,
        offset=offset,
        limit=min(limit, 1000),
    )
    return UserMemoryDataListResult(
        memory_user_id=memory_user_id,
        items=page.items,
        total=page.total,
        offset=offset,
        limit=limit,
    )


async def user_has_memory_data(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
) -> UserMemoryDataExistsResult:
    """Return whether the user has any active memory data."""
    has_data = await mongo_store.has_memory_data_for_user(
        ctx.tenant_id,
        ctx.org_id,
        memory_user_id,
    )
    return UserMemoryDataExistsResult(
        memory_user_id=memory_user_id,
        has_data=has_data,
    )


async def delete_all_for_user(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
) -> UserMemoryDataDeleteResult:
    """Mark all memory data deleted; excluded from list/get/retrieve (not purged)."""
    deleted_count = await mongo_store.soft_delete_all_memory_data_for_user(
        ctx.tenant_id,
        ctx.org_id,
        memory_user_id,
    )
    vector_marked_count = await qdrant_store.mark_vectors_deleted_for_user(
        ctx.tenant_id,
        ctx.org_id,
        memory_user_id,
    )
    return UserMemoryDataDeleteResult(
        memory_user_id=memory_user_id,
        deleted_count=deleted_count,
        vector_marked_count=vector_marked_count,
    )
