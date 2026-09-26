"""Memory data service (Mongo + Qdrant)."""

import asyncio
import json
import logging
import time
from typing import Any

from memory_engine.constants.user_memory_item import (
    MEMORY_RECENTLY_USED_LABELS,
    normalize_memory_source,
    resolve_write_memory_source,
)
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError, ValidationError
from memory_engine.config import get_settings
from memory_engine.db.session import release_db_connection
from memory_engine.integrations import llm_client, mongo_store, qdrant_index_queue, qdrant_store
from memory_engine.schemas.common import SearchMode
from memory_engine.schemas.memory_field import (
    MemoryDataCreate,
    MemoryDataListPage,
    MemoryDataOut,
    MemoryDataUpdate,
    MemoryMarkUsedRequest,
    MemoryMarkUsedResult,
    UserMemoryDataDeleteResult,
    UserMemoryDataExistsResult,
    UserMemoryDataListResult,
)
from memory_engine.services import billing_service
from memory_engine.services import memory_field as mf_service
from memory_engine.services import memory_merge
from memory_engine.services import memory_parse
from memory_engine.services.memory_parse import log_runtime_monitor
from memory_engine.services import memory_claim
from memory_engine.services import rules as rule_service
from memory_engine.services import data_search
from memory_engine.services.original_expression import extract_original_expression
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _dual_write_claim_best_effort(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_id: str,
    memory_field_name: str,
    value: Any,
    source: str | None,
    original_expression: str | None,
    extra: dict[str, Any] | None,
) -> None:
    """Mirror successful V1 writes into V2 without changing V1 availability."""
    try:
        await memory_claim.ingest_legacy_projection(
            session,
            ctx,
            user_id=user_id,
            memory_field_name=memory_field_name,
            value=value,
            source=source,
            original_expression=original_expression,
            extra=extra,
        )
    except Exception as exc:
        logger.warning(
            "memory claim dual write skipped user_id=%s field=%s: %s",
            user_id,
            memory_field_name,
            exc,
        )


_MEMORY_SUMMARY_SYSTEM = """你是个人记忆文档整理助手。请根据提供的记忆条目，形成一个结构化的"用户画像"，并根据"用户画像"为用户整理一份专属记忆文档。

字段含义：
- memory_field_name：该记忆所属领域
- value：记忆的具体内容
- updated_at：记忆更新时间（仅用于判断重要度与时效，禁止写入文档）
- source：记忆来源，例如日程、会议、对话等（仅用于判断重要度与可信度，禁止原封不动写入文档）
- create_time：记忆创建时间（仅用于判断重要度与时效，禁止写入文档）

硬性要求：
1. 严格依据给定字段事实整理，不得臆造、补全或添加未出现的内容。
2. updated_at、create_time、source 只用于内部重要度判别，markdown 中不要写出某个记忆的创建时间和更新时间或来源字样。
3. 将记忆内容加工为清晰事实陈述，按领域组织，逻辑清晰、语义连贯。
4. 仅输出 markdown 正文，不要解释过程，不要输出 JSON。"""

# Circuit breaker for primary LLM used only by _summarize_user_memory_markdown.
# Closed -> Open (300s) with active ping every 45s; cooldown end -> Half-Open (1 real request).
_SUMMARY_CB_STATE = "closed"  # closed | open | half_open
_SUMMARY_PRIMARY_FAILS = 0
_SUMMARY_PRIMARY_OPEN_UNTIL = 0.0
_SUMMARY_CB_FAIL_THRESHOLD = 2
_SUMMARY_CB_OPEN_SECONDS = 300.0
_SUMMARY_CB_PING_INTERVAL_SECONDS = 45.0
_SUMMARY_HALF_OPEN_IN_FLIGHT = False
_SUMMARY_PROBE_TASK: asyncio.Task | None = None
_SUMMARY_CB_GENERATION = 0
_SUMMARY_CB_LOCK = asyncio.Lock()


def _close_summary_primary_circuit() -> None:
    """Transition circuit to Closed."""
    global _SUMMARY_CB_STATE, _SUMMARY_PRIMARY_FAILS, _SUMMARY_PRIMARY_OPEN_UNTIL
    global _SUMMARY_HALF_OPEN_IN_FLIGHT

    _SUMMARY_CB_STATE = "closed"
    _SUMMARY_PRIMARY_FAILS = 0
    _SUMMARY_PRIMARY_OPEN_UNTIL = 0.0
    _SUMMARY_HALF_OPEN_IN_FLIGHT = False


def _trip_summary_primary_circuit(model: str) -> None:
    """Open circuit for long cooldown and start short-interval active pings."""
    global _SUMMARY_CB_STATE, _SUMMARY_PRIMARY_OPEN_UNTIL, _SUMMARY_PRIMARY_FAILS
    global _SUMMARY_HALF_OPEN_IN_FLIGHT, _SUMMARY_PROBE_TASK, _SUMMARY_CB_GENERATION

    _SUMMARY_CB_STATE = "open"
    _SUMMARY_PRIMARY_FAILS = 0
    _SUMMARY_HALF_OPEN_IN_FLIGHT = False
    _SUMMARY_PRIMARY_OPEN_UNTIL = time.monotonic() + _SUMMARY_CB_OPEN_SECONDS
    _SUMMARY_CB_GENERATION += 1
    generation = _SUMMARY_CB_GENERATION
    if _SUMMARY_PROBE_TASK is not None and not _SUMMARY_PROBE_TASK.done():
        _SUMMARY_PROBE_TASK.cancel()
    _SUMMARY_PROBE_TASK = asyncio.create_task(
        _summary_primary_ping_loop(model, generation)
    )
    logger.warning(
        "memory summary primary LLM circuit open for %.0fs; ping every %.0fs",
        _SUMMARY_CB_OPEN_SECONDS,
        _SUMMARY_CB_PING_INTERVAL_SECONDS,
    )


async def _summary_primary_ping_loop(model: str, generation: int) -> None:
    """While Open: ping every 45s; success -> Closed; cooldown end -> Half-Open."""
    global _SUMMARY_CB_STATE, _SUMMARY_HALF_OPEN_IN_FLIGHT

    try:
        while True:
            async with _SUMMARY_CB_LOCK:
                if generation != _SUMMARY_CB_GENERATION or _SUMMARY_CB_STATE != "open":
                    return
                remaining = _SUMMARY_PRIMARY_OPEN_UNTIL - time.monotonic()
                if remaining <= 0:
                    _SUMMARY_CB_STATE = "half_open"
                    _SUMMARY_HALF_OPEN_IN_FLIGHT = False
                    logger.info(
                        "memory summary primary LLM cooldown elapsed; half-open"
                    )
                    return
                sleep_for = min(_SUMMARY_CB_PING_INTERVAL_SECONDS, remaining)

            await asyncio.sleep(sleep_for)

            async with _SUMMARY_CB_LOCK:
                if generation != _SUMMARY_CB_GENERATION or _SUMMARY_CB_STATE != "open":
                    return
                if time.monotonic() >= _SUMMARY_PRIMARY_OPEN_UNTIL:
                    _SUMMARY_CB_STATE = "half_open"
                    _SUMMARY_HALF_OPEN_IN_FLIGHT = False
                    logger.info(
                        "memory summary primary LLM cooldown elapsed; half-open"
                    )
                    return

            try:
                await llm_client.chat_completion(
                    "ping",
                    system="Reply with exactly: ok",
                    model=model,
                    llm_params={"max_tokens": 8},
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("memory summary primary LLM ping failed: %s", exc)
                continue

            async with _SUMMARY_CB_LOCK:
                if generation != _SUMMARY_CB_GENERATION or _SUMMARY_CB_STATE != "open":
                    return
                _close_summary_primary_circuit()
                logger.info("memory summary primary LLM ping ok; circuit closed")
                return
    except asyncio.CancelledError:
        raise


async def _try_primary_summary_completion(
    user_prompt: str,
    model: str,
) -> tuple[str, int, int] | None:
    """Call primary under Closed / Half-Open rules; None means skip to fallback."""
    global _SUMMARY_CB_STATE, _SUMMARY_PRIMARY_FAILS, _SUMMARY_HALF_OPEN_IN_FLIGHT

    async with _SUMMARY_CB_LOCK:
        state = _SUMMARY_CB_STATE
        if state == "open":
            if time.monotonic() >= _SUMMARY_PRIMARY_OPEN_UNTIL:
                _SUMMARY_CB_STATE = "half_open"
                _SUMMARY_HALF_OPEN_IN_FLIGHT = False
                state = "half_open"
                logger.info(
                    "memory summary primary LLM cooldown elapsed; half-open"
                )
            else:
                logger.info(
                    "memory summary primary LLM circuit open; skip to fallback"
                )
                return None

        if state == "half_open":
            if _SUMMARY_HALF_OPEN_IN_FLIGHT:
                logger.info(
                    "memory summary primary LLM half-open busy; skip to fallback"
                )
                return None
            _SUMMARY_HALF_OPEN_IN_FLIGHT = True
            is_half_open_probe = True
        elif state == "closed":
            is_half_open_probe = False
        else:
            return None

    try:
        raw, pt, ct = await llm_client.chat_completion(
            user_prompt,
            system=_MEMORY_SUMMARY_SYSTEM,
            model=model,
        )
        async with _SUMMARY_CB_LOCK:
            if is_half_open_probe:
                _close_summary_primary_circuit()
                logger.info(
                    "memory summary primary LLM half-open probe ok; circuit closed"
                )
            else:
                _SUMMARY_PRIMARY_FAILS = 0
        return raw, pt, ct
    except Exception as exc:
        async with _SUMMARY_CB_LOCK:
            if is_half_open_probe:
                logger.warning(
                    "memory summary primary LLM half-open probe failed: %s", exc
                )
                _trip_summary_primary_circuit(model)
            else:
                _SUMMARY_PRIMARY_FAILS += 1
                logger.warning(
                    "memory summary primary LLM failed (%s/%s): %s",
                    _SUMMARY_PRIMARY_FAILS,
                    _SUMMARY_CB_FAIL_THRESHOLD,
                    exc,
                )
                if _SUMMARY_PRIMARY_FAILS >= _SUMMARY_CB_FAIL_THRESHOLD:
                    _trip_summary_primary_circuit(model)
        return None
    finally:
        # CancelledError (BaseException) bypasses except Exception; always release
        # the half-open probe slot so a later request can retry the primary.
        if is_half_open_probe:
            async with _SUMMARY_CB_LOCK:
                if _SUMMARY_HALF_OPEN_IN_FLIGHT:
                    _SUMMARY_HALF_OPEN_IN_FLIGHT = False


def _memory_facts_for_summary(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick only the fields needed for personal memory markdown summarization."""
    facts: list[dict[str, Any]] = []
    for d in docs:
        facts.append(
            {
                "memory_field_name": d.get("memory_field_name"),
                "value": d.get("value"),
                "updated_at": d.get("updated_at"),
                "source": d.get("source"),
                "create_time": d.get("create_time"),
            }
        )
    return facts


async def _summarize_user_memory_markdown(
    session: AsyncSession,
    ctx: RequestContext,
    docs: list[dict[str, Any]],
) -> str | None:
    """
    Ask LLM to turn memory facts into a personal markdown memory document.
    """
    if not docs:
        return None
    facts = _memory_facts_for_summary(docs)
    user_prompt = (
        "以下是该用户的全部记忆条目（JSON）。请综合整理成一份专属记忆文档，以 markdown 输出：\n\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    settings = get_settings()
    model = settings.openai_model
    fallback_model = settings.deepseek_v4_pro_model
    fallback_base_url = settings.deepseek_v4_pro_base_url or None
    fallback_api_key = settings.deepseek_v4_pro_api_key or None

    raw: str | None = None
    pt = 0
    ct = 0
    used_model = model
    primary_ok = False

    primary_result = await _try_primary_summary_completion(user_prompt, model)
    if primary_result is not None:
        raw, pt, ct = primary_result
        primary_ok = True
        used_model = model

    if not primary_ok:
        if not fallback_model and not fallback_base_url:
            return None
        try:
            used_model = fallback_model or model
            raw, pt, ct = await llm_client.chat_completion(
                user_prompt,
                system=_MEMORY_SUMMARY_SYSTEM,
                model=used_model,
                base_url=fallback_base_url,
                api_key=fallback_api_key,
            )
        except Exception as exc:
            logger.warning("memory summary fallback LLM failed: %s", exc)
            return None

    await billing_service.emit_llm_completion(
        session, ctx, model_name=used_model, prompt_tokens=pt, completion_tokens=ct
    )
    text = (raw or "").strip()
    return text or None


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
    source: str | None = None,
    language: str,
) -> tuple[Any, str]:
    """``MERGE`` writes use merge_rule + LLM to fuse old/new; result stored via OVERWRITE."""
    if match_method != "MERGE":
        log_runtime_monitor(
            "记忆融合 · 跳过",
            [
                ("匹配方法名", match_method),
                ("原因", "非 MERGE，无需融合"),
            ],
        )
        return value, match_method

    existing = await mongo_store.get_memory_data(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name, source=source
    )
    if not existing or existing.get("deleted") == 1:
        log_runtime_monitor(
            "记忆融合 · 跳过",
            [
                ("匹配方法名", match_method),
                ("原因", "无有效已有内容，直接写入新值"),
            ],
        )
        return value, match_method

    resolved_rule = await _resolve_merge_rule_name(
        session, ctx, memory_field_name, merge_rule_name
    )
    if not resolved_rule:
        raise ValidationError(
            f"memory_field '{memory_field_name}' uses match_method MERGE but no merge_rule "
            f"is registered (register via POST /schema/merge/create or Schema.getOrCreate merge_rule)"
        )
    log_runtime_monitor(
        "记忆融合 · 准备执行",
        [
            ("融合规则", resolved_rule),
        ],
    )
    merged = await memory_merge.merge_with_rule(
        session,
        ctx,
        memory_field_name=memory_field_name,
        old_value=existing.get("value"),
        new_value=value,
        rule_name=resolved_rule,
        language=language,
    )
    return merged, "OVERWRITE"


async def _index_vector_async(
    storage_type: str,
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
    if storage_type not in ("VECTOR", "KV_AND_VECTOR"):
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
        log_runtime_monitor(
            "记忆解析 · 直写路径",
            [
                ("记忆领域", body.memory_field_name),
                ("路径说明", "请求已带 value，跳过 parse_rule LLM 解析，仅做语言翻译"),
                ("原始输入 query", body.query),
                ("直写 value", body.value),
                ("目标语言", body.language or "en-US"),
            ],
        )
        return await memory_parse._translate_value(
            body.value, body.language or "en-US", session, ctx
        )
    raw = body.query or ""
    log_runtime_monitor(
        "记忆解析 · 开始",
        [
            ("记忆领域", body.memory_field_name),
            ("解析规则名", body.parse_rule_name or "（未指定）"),
            ("原始输入 query", raw),
            ("目标语言", body.language),
            ("extra", body.extra),
        ],
    )
    return await memory_parse.parse_with_rule(
        session,
        ctx,
        memory_field_name=body.memory_field_name,
        rule_name=body.parse_rule_name,
        raw_query=raw,
        extra=body.extra,
        output_language=body.language,
    )


def _resolve_original_expression(
    *,
    query: str | None,
    value: Any,
    explicit: str | None,
) -> str | None:
    """Resolve original expression from explicit payload or query/value span."""
    return extract_original_expression(query, value, explicit=explicit)


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
    field = await _get_field(session, ctx, body.memory_field_name)
    field_storage_type = field.storage_type
    match_method = _match_method(field, body.write_rule)
    try:
        memory_source = resolve_write_memory_source(body.source, body.parse_rule_name)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    log_runtime_monitor(
        "记忆写入 create · 请求概览",
        [
            ("用户 ID", body.user_id),
            ("记忆领域", body.memory_field_name),
            ("匹配方法 match_method", match_method),
            ("来源 source", memory_source),
            ("解析规则 parse_rule_name", body.parse_rule_name or "（无）"),
            ("融合规则 merge_rule_name", body.merge_rule_name or "（无，运行时自动解析）"),
            ("原始输入 query", body.query),
            ("直写 value", body.value if body.value is not None else "（无，走 query 解析）"),
            ("语言 language", body.language),
        ],
    )

    # start parse user query
    await release_db_connection(session)
    value = await _resolve_value(session, ctx, body)
    existing = await mongo_store.get_memory_data(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.memory_field_name,
        source=memory_source,
    )
    existing_value = (
        existing.get("value")
        if existing and existing.get("deleted") == 0
        else None
    )
    log_runtime_monitor(
        "记忆写入 create · 解析完成",
        [
            ("已有内容 existing", existing_value if existing_value is not None else "（无有效已有内容）"),
        ],
    )
    if memory_parse.parse_result_is_empty(value):
        log_runtime_monitor(
            "记忆写入 create · 结束",
            [
                ("结果", "解析结果为空，跳过写入"),
                ("返回已有内容", existing_value if existing_value is not None else "（无）"),
            ],
        )
        return _out_without_write(body, existing)

    # Span is based on the newly parsed/written payload (not post-merge text).
    original_expression = _resolve_original_expression(
        query=body.query,
        value=body.value if body.value is not None else value,
        explicit=body.original_expression,
    )

    if existing and existing.get("deleted") == 0:
        value, effective_match = await _apply_merge_strategy(
            session,
            ctx,
            user_id=body.user_id,
            memory_field_name=body.memory_field_name,
            value=value,
            match_method=match_method,
            merge_rule_name=body.merge_rule_name,
            source=memory_source,
            language=body.language,
        )
        if memory_parse.parse_result_is_empty(value):
            log_runtime_monitor(
                "记忆写入 create · 结束",
                [
                    ("结果", "融合后内容为空，跳过写入"),
                    ("返回已有内容", existing_value),
                ],
            )
            return _out_without_write(body, existing)
        log_runtime_monitor(
            "记忆写入 create · 转入 update",
            [
                ("原匹配方法", match_method),
                ("生效匹配方法", effective_match),
                ("融合/待写入内容", value),
            ],
        )
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
                query=body.query,
                extra=body.extra,
                # Prefer pre-merge span; do not re-extract against merged text.
                original_expression=original_expression,
            ),
        )

    doc = await mongo_store.upsert_memory_data(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.memory_field_name,
        value,
        match_method=match_method,
        source=memory_source,
        original_expression=original_expression,
    )
    await _index_vector_async(
        field_storage_type,
        ctx,
        body.user_id,
        body.memory_field_name,
        doc["_id"],
        doc["value"],
    )
    await _dual_write_claim_best_effort(
        session,
        ctx,
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
        source=memory_source,
        original_expression=original_expression,
        extra=body.extra,
    )
    log_runtime_monitor(
        "记忆写入 create · 新建完成",
        [
            ("记忆领域", body.memory_field_name),
            ("来源 source", memory_source),
            ("匹配方法", match_method),
            ("最终写入内容", "规范化后解析结果"),
        ],
    )
    return MemoryDataOut(
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
    )


async def update(session: AsyncSession, ctx: RequestContext, body: MemoryDataUpdate) -> MemoryDataOut:
    field = await _get_field(session, ctx, body.memory_field_name)
    field_storage_type = field.storage_type
    try:
        memory_source = normalize_memory_source(body.source)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    match_method = _match_method(field, body.write_rule)
    log_runtime_monitor(
        "记忆更新 update · 请求概览",
        [
            ("用户 ID", body.user_id),
            ("记忆领域", body.memory_field_name),
            ("匹配方法 match_method", match_method),
            ("来源 source", memory_source),
            ("融合规则 merge_rule_name", body.merge_rule_name or "（无，运行时自动解析）"),
            ("原始输入 query", body.query),
            ("待写入 value", body.value),
            ("语言 language", body.language),
        ],
    )

    await release_db_connection(session)
    if memory_parse.parse_result_is_empty(body.value):
        existing = await mongo_store.get_memory_data(
            ctx.tenant_id,
            ctx.org_id,
            body.user_id,
            body.memory_field_name,
            source=memory_source,
        )
        if existing and existing.get("deleted") == 0:
            log_runtime_monitor(
                "记忆更新 update · 结束",
                [
                    ("结果", "待写入 value 为空，保留已有内容"),
                    ("已有内容 existing", existing.get("value")),
                ],
            )
            return MemoryDataOut(
                user_id=body.user_id,
                memory_field_name=body.memory_field_name,
                value=existing.get("value"),
            )
        raise NotFoundError("memory data not found")
    # Prefer expression against the inbound (pre-merge) value when query is present.
    inbound_expression = _resolve_original_expression(
        query=body.query,
        value=body.value,
        explicit=body.original_expression,
    )
    value, effective_match = await _apply_merge_strategy(
        session,
        ctx,
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=body.value,
        match_method=match_method,
        merge_rule_name=body.merge_rule_name,
        source=memory_source,
        language=body.language,
    )
    doc = await mongo_store.upsert_memory_data(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.memory_field_name,
        value,
        match_method=effective_match,
        source=memory_source,
        original_expression=inbound_expression,
    )
    await _index_vector_async(
        field_storage_type,
        ctx,
        body.user_id,
        body.memory_field_name,
        doc["_id"],
        doc["value"],
    )
    await _dual_write_claim_best_effort(
        session,
        ctx,
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
        source=memory_source,
        original_expression=inbound_expression,
        extra=body.extra,
    )
    log_runtime_monitor(
        "记忆更新 update · 完成",
        [
            ("最终写入内容", "融合后整合结果"),
        ],
    )
    return MemoryDataOut(
        user_id=body.user_id,
        memory_field_name=body.memory_field_name,
        value=doc["value"],
    )


async def mark_used(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryMarkUsedRequest,
) -> MemoryMarkUsedResult:
    """Record recent use label on memory rows (algorithm retrieve path)."""
    _ = session
    try:
        usage = normalize_memory_source(body.usage)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if usage is None:
        raise ValidationError("usage is required")
    label = MEMORY_RECENTLY_USED_LABELS.get(usage)
    if not label:
        raise ValidationError(f"unsupported usage '{body.usage}'")
    updated = await mongo_store.mark_memory_data_recently_used(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        recently_used=label,
        memory_field_names=body.memory_field_names,
        item_ids=body.item_ids,
    )
    return MemoryMarkUsedResult(updated=updated, recently_used=label)


async def delete_soft(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str,
    memory_field_name: str,
    source: str | None = None,
) -> None:
    field = await _get_field(session, ctx, memory_field_name)
    field_storage_type = field.storage_type
    try:
        memory_source = normalize_memory_source(source)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    ok = await mongo_store.soft_delete_memory_data(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name, source=memory_source
    )
    if not ok:
        raise NotFoundError("memory data not found")
    doc_id = mongo_store._doc_id(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name, source=memory_source
    )
    await _index_vector_async(
        field_storage_type,
        ctx,
        user_id,
        memory_field_name,
        doc_id,
        "",
        action="delete",
    )


async def get(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str,
    memory_field_name: str,
    *,
    mode: SearchMode = SearchMode.EXACT,
    query: str = "",
    source: str | None = None,
) -> MemoryDataOut:
    await _get_field(session, ctx, memory_field_name)
    if mode == SearchMode.EXACT and not query:
        try:
            memory_source = normalize_memory_source(source)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        doc = await mongo_store.get_memory_data(
            ctx.tenant_id,
            ctx.org_id,
            user_id,
            memory_field_name,
            source=memory_source,
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



async def list_for_user_page_md(
    session: AsyncSession,
    ctx: RequestContext,
    user_id: str,
    *,
    memory_field_name: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    if memory_field_name:
        await _get_field(session, ctx, memory_field_name)
    docs = await mongo_store.list_memory_data_for_user(
        ctx.tenant_id,
        ctx.org_id,
        user_id,
        memory_field_name=memory_field_name,
        offset=offset,
        limit=limit,
    )

    # LLM personal memory markdown (generation only; further wiring comes later).
    _memory_summary_md = await _summarize_user_memory_markdown(session, ctx, docs)

    return {
        "user_id": user_id,
        "markdown": _memory_summary_md,
    }


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


async def list_all_for_user_md(
    session: AsyncSession,
    ctx: RequestContext,
    memory_user_id: str,
    *,
    offset: int = 0,
    limit: int = 500,
) -> dict[str, Any]:
    """List all active memory data for a Mongo/Qdrant partition (service API)."""
    page = await list_for_user_page_md(
        session,
        ctx,
        memory_user_id,
        offset=offset,
        limit=min(limit, 1000),
    )
    return {
        "user_id": page["user_id"],
        "markdown": page["markdown"],
        "offset": offset,
        "limit": limit,
    }


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
