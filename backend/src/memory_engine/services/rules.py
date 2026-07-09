"""Parse / retrieve / call rule CRUD."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError, NotFoundError, ValidationError
from memory_engine.models.schema import CallRule, MergeRule, ParseRule, RetrieveRule
from memory_engine.schemas.rules import (
    CallRuleCreate,
    RetrieveRuleCreate,
    RuleOut,
    RuleUpdateBody,
)
from memory_engine.integrations import schema_sync
from memory_engine.services import capability_registry as cap_service
from memory_engine.services import memory_field as mf_service

T = TypeVar("T", ParseRule, MergeRule, RetrieveRule, CallRule)


def _rule_out(row: Any, *, extra: dict | None = None) -> RuleOut:
    data = {
        "id": row.id,
        "rule_name": row.rule_name,
        "version": row.version,
        "memory_field_name": getattr(row, "memory_field_name", None),
        "retrieve_method": getattr(row, "retrieve_method", None),
        "slot_name": getattr(row, "slot_name", None),
        "rule_config_json": row.rule_config_json,
        "priority": getattr(row, "priority", 0),
    }
    if extra:
        data.update(extra)
    return RuleOut(**data)


async def _next_version(
    session: AsyncSession, model: type[T], ctx: RequestContext, **filters: Any
) -> int:
    # Max over all rows (incl. soft-deleted) — uk_*_version is unique per version number.
    stmt = select(func.coalesce(func.max(model.version), 0)).where(
        model.tenant_id == ctx.tenant_id,
        model.org_id == ctx.org_id,
    )
    for key, val in filters.items():
        if val is not None:
            stmt = stmt.where(getattr(model, key) == val)
    result = await session.execute(stmt)
    return int(result.scalar_one()) + 1


# ---------- Parse ----------


async def create_parse(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    memory_field_name: str,
    rule_name: str,
    rule_config_json: dict | None = None,
    capability_id: int | None = None,
    capability_name: str | None = None,
    module_name: str | None = None,
    service_name: str | None = None,
    code_fingerprint: str | None = None,
    priority: int = 0,
) -> ParseRule:
    mf = await mf_service.get_active_by_name(session, ctx, memory_field_name)
    if not mf:
        raise NotFoundError(f"memory_field '{memory_field_name}' not found")
    cap_id = await cap_service.resolve_capability_id(
        session,
        ctx,
        capability_id=capability_id,
        capability_name=capability_name,
        module_name=module_name,
        service_name=service_name,
        rule_kind="parse",
        config_json=rule_config_json,
        code_fingerprint=code_fingerprint,
    )
    current = await get_active_parse(session, ctx, memory_field_name, rule_name)
    if current:
        await session.execute(
            update(ParseRule).where(ParseRule.id == current.id).values(
                deleted=1, updated_by=ctx.user_id
            )
        )
    version = await _next_version(
        session, ParseRule, ctx, memory_field_id=mf.id, rule_name=rule_name
    )
    row = ParseRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=mf.id,
        memory_field_name=memory_field_name,
        rule_name=rule_name,
        capability_id=cap_id,
        rule_config_json=rule_config_json,
        priority=priority,
        version=version,
        source="sdk" if module_name else "api",
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await schema_sync.publish_rule_change(
        table="parse_rule",
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_name=memory_field_name,
        event_type="create",
        version=version,
        payload={
            "rule_name": rule_name,
            "memory_field_name": memory_field_name,
            "capability_id": cap_id,
            "version": version,
        },
    )
    return row


async def get_active_parse(
    session: AsyncSession, ctx: RequestContext, memory_field_name: str, rule_name: str
) -> ParseRule | None:
    """Latest active parse rule: ``deleted=0``, highest ``version`` for ``rule_name``."""
    result = await session.execute(
        select(ParseRule)
        .where(
            ParseRule.tenant_id == ctx.tenant_id,
            ParseRule.org_id == ctx.org_id,
            ParseRule.memory_field_name == memory_field_name,
            ParseRule.rule_name == rule_name,
            ParseRule.deleted == 0,
        )
        .order_by(ParseRule.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_parse(session: AsyncSession, ctx: RequestContext, limit: int = 100) -> list[ParseRule]:
    result = await session.execute(
        select(ParseRule)
        .where(
            ParseRule.tenant_id == ctx.tenant_id,
            ParseRule.org_id == ctx.org_id,
            ParseRule.deleted == 0,
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_parse(
    session: AsyncSession,
    ctx: RequestContext,
    memory_field_name: str,
    rule_name: str,
    body: RuleUpdateBody,
) -> ParseRule:
    current = await get_active_parse(session, ctx, memory_field_name, rule_name)
    if not current:
        raise NotFoundError("parse_rule not found")
    await session.execute(
        update(ParseRule).where(ParseRule.id == current.id).values(deleted=1, updated_by=ctx.user_id)
    )
    version = await _next_version(
        session, ParseRule, ctx, memory_field_id=current.memory_field_id, rule_name=rule_name
    )
    row = ParseRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=current.memory_field_id,
        memory_field_name=memory_field_name,
        rule_name=rule_name,
        capability_id=body.capability_id if body.capability_id is not None else current.capability_id,
        rule_config_json=body.rule_config_json or current.rule_config_json,
        priority=body.priority if body.priority is not None else current.priority,
        version=version,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    return row


async def delete_parse_soft(
    session: AsyncSession, ctx: RequestContext, memory_field_name: str, rule_name: str
) -> None:
    current = await get_active_parse(session, ctx, memory_field_name, rule_name)
    if not current:
        raise NotFoundError("parse_rule not found")
    current.deleted = 1
    current.updated_by = ctx.user_id
    await session.commit()


# ---------- Merge (LLM fusion for MERGE match_method) ----------


async def create_merge(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    memory_field_name: str,
    rule_name: str,
    rule_config_json: dict | None = None,
    capability_id: int | None = None,
    priority: int = 0,
) -> MergeRule:
    from memory_engine.services.memory_merge import validate_merge_prompt

    mf = await mf_service.get_active_by_name(session, ctx, memory_field_name)
    if not mf:
        raise NotFoundError(f"memory_field '{memory_field_name}' not found")
    if mf.match_method != "MERGE":
        raise ValidationError(
            f"memory_field '{memory_field_name}' match_method must be MERGE to register merge_rule"
        )
    prompt = (rule_config_json or {}).get("prompt", "")
    validate_merge_prompt(prompt)

    current = await get_active_merge(session, ctx, memory_field_name, rule_name)
    if current:
        await session.execute(
            update(MergeRule).where(MergeRule.id == current.id).values(
                deleted=1, updated_by=ctx.user_id
            )
        )
    version = await _next_version(
        session, MergeRule, ctx, memory_field_id=mf.id, rule_name=rule_name
    )
    row = MergeRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=mf.id,
        memory_field_name=memory_field_name,
        rule_name=rule_name,
        capability_id=capability_id,
        rule_config_json=rule_config_json,
        priority=priority,
        version=version,
        source="api",
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await schema_sync.publish_rule_change(
        table="merge_rule",
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_name=memory_field_name,
        event_type="create",
        version=version,
        payload={
            "rule_name": rule_name,
            "memory_field_name": memory_field_name,
            "version": version,
        },
    )
    return row


async def get_active_merge(
    session: AsyncSession, ctx: RequestContext, memory_field_name: str, rule_name: str
) -> MergeRule | None:
    result = await session.execute(
        select(MergeRule)
        .where(
            MergeRule.tenant_id == ctx.tenant_id,
            MergeRule.org_id == ctx.org_id,
            MergeRule.memory_field_name == memory_field_name,
            MergeRule.rule_name == rule_name,
            MergeRule.deleted == 0,
        )
        .order_by(MergeRule.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_merge(session: AsyncSession, ctx: RequestContext, limit: int = 100) -> list[MergeRule]:
    result = await session.execute(
        select(MergeRule)
        .where(
            MergeRule.tenant_id == ctx.tenant_id,
            MergeRule.org_id == ctx.org_id,
            MergeRule.deleted == 0,
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_merge_soft(
    session: AsyncSession, ctx: RequestContext, memory_field_name: str, rule_name: str
) -> None:
    current = await get_active_merge(session, ctx, memory_field_name, rule_name)
    if not current:
        raise NotFoundError("merge_rule not found")
    current.deleted = 1
    current.updated_by = ctx.user_id
    await session.commit()


# ---------- Retrieve ----------


async def create_retrieve(
    session: AsyncSession, ctx: RequestContext, body: RetrieveRuleCreate
) -> RetrieveRule:
    mf_id: int | None = None
    mf_name: str | None = body.memory_field_name
    if body.memory_field_name:
        mf = await mf_service.get_active_by_name(session, ctx, body.memory_field_name)
        if not mf:
            raise NotFoundError(f"memory_field '{body.memory_field_name}' not found")
        mf_id = mf.id
    version = await _next_version(session, RetrieveRule, ctx, rule_name=body.rule_name)
    row = RetrieveRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=mf_id,
        memory_field_name=mf_name,
        rule_name=body.rule_name,
        retrieve_method=body.retrieve_method,
        capability_id=body.capability_id,
        rule_config_json=body.rule_config_json,
        priority=body.priority,
        version=version,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    return row


async def get_active_retrieve(
    session: AsyncSession,
    ctx: RequestContext,
    rule_name: str,
    *,
    memory_field_name: str | None = None,
    implicit: bool = False,
) -> RetrieveRule | None:
    stmt = select(RetrieveRule).where(
        RetrieveRule.tenant_id == ctx.tenant_id,
        RetrieveRule.org_id == ctx.org_id,
        RetrieveRule.rule_name == rule_name,
        RetrieveRule.deleted == 0,
    )
    if implicit:
        stmt = stmt.where(RetrieveRule.memory_field_id.is_(None))
    elif memory_field_name:
        stmt = stmt.where(RetrieveRule.memory_field_name == memory_field_name)
    stmt = stmt.order_by(RetrieveRule.version.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_retrieve(session: AsyncSession, ctx: RequestContext, limit: int = 100) -> list[RetrieveRule]:
    result = await session.execute(
        select(RetrieveRule)
        .where(
            RetrieveRule.tenant_id == ctx.tenant_id,
            RetrieveRule.org_id == ctx.org_id,
            RetrieveRule.deleted == 0,
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_retrieve(
    session: AsyncSession,
    ctx: RequestContext,
    rule_name: str,
    body: RuleUpdateBody,
    *,
    memory_field_name: str | None = None,
) -> RetrieveRule:
    current = await get_active_retrieve(session, ctx, rule_name, memory_field_name=memory_field_name)
    if not current:
        raise NotFoundError("retrieve_rule not found")
    await session.execute(
        update(RetrieveRule).where(RetrieveRule.id == current.id).values(deleted=1, updated_by=ctx.user_id)
    )
    version = await _next_version(session, RetrieveRule, ctx, rule_name=rule_name)
    row = RetrieveRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=current.memory_field_id,
        memory_field_name=current.memory_field_name,
        rule_name=rule_name,
        retrieve_method=body.retrieve_method or current.retrieve_method,
        capability_id=body.capability_id if body.capability_id is not None else current.capability_id,
        rule_config_json=body.rule_config_json or current.rule_config_json,
        priority=body.priority if body.priority is not None else current.priority,
        version=version,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    return row


async def delete_retrieve_soft(
    session: AsyncSession,
    ctx: RequestContext,
    rule_name: str,
    *,
    memory_field_name: str | None = None,
) -> None:
    current = await get_active_retrieve(session, ctx, rule_name, memory_field_name=memory_field_name)
    if not current:
        raise NotFoundError("retrieve_rule not found")
    current.deleted = 1
    current.updated_by = ctx.user_id
    await session.commit()


def retrieve_rule_to_body(row: RetrieveRule) -> dict[str, Any]:
    """Map DB retrieve_rule to API retrieve request rule body."""
    cfg = row.rule_config_json or {}
    llm_cfg = cfg.get("llm")
    return {
        "method": row.retrieve_method,
        "prompt": cfg.get("prompt"),
        "llm": llm_cfg,
    }


# ---------- Call ----------


async def create_call(
    session: AsyncSession, ctx: RequestContext, body: CallRuleCreate
) -> CallRule:
    mf = await mf_service.get_active_by_name(session, ctx, body.memory_field_name)
    if not mf:
        raise NotFoundError(f"memory_field '{body.memory_field_name}' not found")
    cap_id = await cap_service.resolve_capability_id(
        session,
        ctx,
        capability_id=body.capability_id,
        capability_name=body.capability_name,
        module_name=body.module_name,
        service_name=body.service_name,
        rule_kind="call",
        slot_name=body.slot_name,
        config_json=body.rule_config_json,
        code_fingerprint=body.code_fingerprint,
    )
    version = await _next_version(
        session, CallRule, ctx, memory_field_id=mf.id, slot_name=body.slot_name
    )
    row = CallRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=mf.id,
        memory_field_name=body.memory_field_name,
        rule_name=body.rule_name,
        slot_name=body.slot_name,
        capability_id=cap_id,
        rule_config_json=body.rule_config_json,
        version=version,
        source="sdk" if body.module_name else "api",
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await schema_sync.publish_rule_change(
        table="call_rule",
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_name=body.memory_field_name,
        event_type="create",
        version=version,
        payload={
            "rule_name": body.rule_name,
            "slot_name": body.slot_name,
            "memory_field_name": body.memory_field_name,
            "capability_id": cap_id,
            "version": version,
        },
    )
    return row


async def get_active_call(
    session: AsyncSession,
    ctx: RequestContext,
    memory_field_name: str,
    rule_name: str,
) -> CallRule | None:
    result = await session.execute(
        select(CallRule)
        .where(
            CallRule.tenant_id == ctx.tenant_id,
            CallRule.org_id == ctx.org_id,
            CallRule.memory_field_name == memory_field_name,
            CallRule.rule_name == rule_name,
            CallRule.deleted == 0,
        )
        .order_by(CallRule.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_call(session: AsyncSession, ctx: RequestContext, limit: int = 100) -> list[CallRule]:
    result = await session.execute(
        select(CallRule)
        .where(
            CallRule.tenant_id == ctx.tenant_id,
            CallRule.org_id == ctx.org_id,
            CallRule.deleted == 0,
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_call(
    session: AsyncSession,
    ctx: RequestContext,
    memory_field_name: str,
    rule_name: str,
    body: RuleUpdateBody,
) -> CallRule:
    current = await get_active_call(session, ctx, memory_field_name, rule_name)
    if not current:
        raise NotFoundError("call_rule not found")
    await session.execute(
        update(CallRule).where(CallRule.id == current.id).values(deleted=1, updated_by=ctx.user_id)
    )
    version = await _next_version(
        session, CallRule, ctx, memory_field_id=current.memory_field_id, slot_name=current.slot_name
    )
    row = CallRule(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_id=current.memory_field_id,
        memory_field_name=memory_field_name,
        rule_name=rule_name,
        slot_name=body.slot_name or current.slot_name,
        capability_id=body.capability_id if body.capability_id is not None else current.capability_id,
        rule_config_json=body.rule_config_json or current.rule_config_json,
        version=version,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    return row


async def delete_call_soft(
    session: AsyncSession, ctx: RequestContext, memory_field_name: str, rule_name: str
) -> None:
    current = await get_active_call(session, ctx, memory_field_name, rule_name)
    if not current:
        raise NotFoundError("call_rule not found")
    current.deleted = 1
    current.updated_by = ctx.user_id
    await session.commit()
