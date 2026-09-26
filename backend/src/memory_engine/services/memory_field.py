"""Memory field business logic."""

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, func, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError, NotFoundError, ValidationError
from memory_engine.integrations import redis_cache, schema_sync
from memory_engine.models.schema import MemoryField
from memory_engine.schemas.common import SearchMode
from memory_engine.schemas.memory_field import MemoryFieldCreate, MemoryFieldOut, MemoryFieldUpdate


def _to_out(row: MemoryField) -> MemoryFieldOut:
    return MemoryFieldOut.model_validate(row)


def _name_lock_key(ctx: RequestContext, name: str) -> str:
    """MySQL advisory lock key for serializing create/update on one field name."""
    return f"mos:mf:{ctx.tenant_id}:{ctx.org_id}:{name}"[:64]


def _validate_json_schema(schema: dict | None) -> None:
    if schema is None:
        return
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValidationError(f"invalid JSON Schema: {exc.message}") from exc


def _validate_policy_json(
    access_policy: dict | None,
    update_policy: dict | None,
    retrieval_policy: dict | None,
) -> None:
    if access_policy is not None:
        from memory_engine.schemas.memory_claim import MemoryAccessPolicy

        try:
            MemoryAccessPolicy.model_validate(access_policy)
        except PydanticValidationError as exc:
            raise ValidationError(f"invalid access policy: {exc.errors()[0]['msg']}") from exc
    if update_policy is not None:
        threshold = update_policy.get("min_confidence")
        try:
            valid_threshold = threshold is None or 0 <= float(threshold) <= 1
        except (TypeError, ValueError):
            valid_threshold = False
        if not valid_threshold:
            raise ValidationError("update_policy.min_confidence must be between 0 and 1")
    if retrieval_policy is not None:
        threshold = retrieval_policy.get("min_score")
        try:
            valid_threshold = threshold is None or 0 <= float(threshold) <= 1
        except (TypeError, ValueError):
            valid_threshold = False
        if not valid_threshold:
            raise ValidationError("retrieval_policy.min_score must be between 0 and 1")
        top_k = retrieval_policy.get("top_k")
        try:
            valid_top_k = top_k is None or 1 <= int(top_k) <= 50
        except (TypeError, ValueError):
            valid_top_k = False
        if not valid_top_k:
            raise ValidationError("retrieval_policy.top_k must be between 1 and 50")


async def _acquire_name_lock(session: AsyncSession, ctx: RequestContext, name: str) -> None:
    """Serialize memory_field mutations per (tenant, org, name) to prevent duplicate actives."""
    result = await session.execute(
        text("SELECT GET_LOCK(:lock_key, :timeout)"),
        {"lock_key": _name_lock_key(ctx, name), "timeout": 10},
    )
    if result.scalar_one() != 1:
        raise ConflictError(f"could not acquire lock for memory_field '{name}'")


async def _release_name_lock(session: AsyncSession, ctx: RequestContext, name: str) -> None:
    await session.execute(
        text("SELECT RELEASE_LOCK(:lock_key)"),
        {"lock_key": _name_lock_key(ctx, name)},
    )


async def _next_version(session: AsyncSession, ctx: RequestContext, name: str) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(MemoryField.version), 0)).where(
            MemoryField.tenant_id == ctx.tenant_id,
            MemoryField.org_id == ctx.org_id,
            MemoryField.name == name,
        )
    )
    return int(result.scalar_one()) + 1


async def get_active_by_name(
    session: AsyncSession, ctx: RequestContext, name: str
) -> MemoryField | None:
    cached = await redis_cache.get_schema_cache(ctx.tenant_id, ctx.org_id, name)
    if cached and cached.get("deleted") != 1 and cached.get("id"):
        result = await session.execute(
            select(MemoryField).where(
                MemoryField.id == cached["id"],
                MemoryField.deleted == 0,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return row
    result = await session.execute(
        select(MemoryField)
        .where(
            MemoryField.tenant_id == ctx.tenant_id,
            MemoryField.org_id == ctx.org_id,
            MemoryField.name == name,
            MemoryField.deleted == 0,
        )
        .order_by(MemoryField.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def search_by_mode(
    session: AsyncSession, ctx: RequestContext, name: str, mode: SearchMode
) -> MemoryField | None:
    from memory_engine.services import schema_search

    return await schema_search.search_schema(session, ctx, name, mode)


async def list_active(
    session: AsyncSession, ctx: RequestContext, *, offset: int = 0, limit: int = 50
) -> list[MemoryField]:
    """List active fields; at most one row per ``name`` (highest ``version``)."""
    latest = (
        select(
            MemoryField.name.label("name"),
            func.max(MemoryField.version).label("max_version"),
        )
        .where(
            MemoryField.tenant_id == ctx.tenant_id,
            MemoryField.org_id == ctx.org_id,
            MemoryField.deleted == 0,
        )
        .group_by(MemoryField.name)
        .subquery()
    )
    result = await session.execute(
        select(MemoryField)
        .join(
            latest,
            and_(
                MemoryField.name == latest.c.name,
                MemoryField.version == latest.c.max_version,
            ),
        )
        .where(
            MemoryField.tenant_id == ctx.tenant_id,
            MemoryField.org_id == ctx.org_id,
            MemoryField.deleted == 0,
        )
        .order_by(MemoryField.update_time.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(
    session: AsyncSession, ctx: RequestContext, body: MemoryFieldCreate
) -> MemoryFieldOut:
    _validate_json_schema(body.json_schema)
    _validate_policy_json(
        body.access_policy_json, body.update_policy_json, body.retrieval_policy_json
    )
    await _acquire_name_lock(session, ctx, body.name)
    try:
        existing = await get_active_by_name(session, ctx, body.name)
        if existing:
            raise ConflictError(f"memory_field '{body.name}' already exists")

        version = await _next_version(session, ctx, body.name)
        row = MemoryField(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            name=body.name,
            description=body.description,
            value_type=body.value_type,
            match_method=body.match_method,
            storage_type=body.storage_type,
            json_schema=body.json_schema,
            schema_version=body.schema_version,
            update_policy_json=body.update_policy_json,
            access_policy_json=body.access_policy_json,
            retrieval_policy_json=body.retrieval_policy_json,
            version=version,
            source=body.source,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(row)
        await session.flush()
        out = _to_out(row)
        await session.commit()
        await schema_sync.publish_memory_field_change(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            memory_field_name=body.name,
            event_type="create",
            deleted=0,
            version=version,
            payload=out.model_dump(),
        )
        return out
    finally:
        await _release_name_lock(session, ctx, body.name)


async def update(
    session: AsyncSession, ctx: RequestContext, name: str, body: MemoryFieldUpdate
) -> MemoryFieldOut:
    _validate_json_schema(body.json_schema)
    _validate_policy_json(
        body.access_policy_json, body.update_policy_json, body.retrieval_policy_json
    )
    await _acquire_name_lock(session, ctx, name)
    try:
        current = await get_active_by_name(session, ctx, name)
        if not current:
            raise NotFoundError(f"memory_field '{name}' not found")

        await session.execute(
            sql_update(MemoryField)
            .where(MemoryField.id == current.id)
            .values(deleted=1, updated_by=ctx.user_id)
        )
        version = await _next_version(session, ctx, name)
        row = MemoryField(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            name=current.name,
            description=body.description if body.description is not None else current.description,
            value_type=body.value_type or current.value_type,
            match_method=body.match_method or current.match_method,
            storage_type=body.storage_type or current.storage_type,
            json_schema=(
                body.json_schema if body.json_schema is not None else current.json_schema
            ),
            schema_version=body.schema_version or current.schema_version,
            update_policy_json=(
                body.update_policy_json
                if body.update_policy_json is not None
                else current.update_policy_json
            ),
            access_policy_json=(
                body.access_policy_json
                if body.access_policy_json is not None
                else current.access_policy_json
            ),
            retrieval_policy_json=(
                body.retrieval_policy_json
                if body.retrieval_policy_json is not None
                else current.retrieval_policy_json
            ),
            version=version,
            status=body.status or current.status,
            source=current.source,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )
        session.add(row)
        await session.flush()
        out = _to_out(row)
        await session.commit()
        await schema_sync.publish_memory_field_change(
            tenant_id=ctx.tenant_id,
            org_id=ctx.org_id,
            memory_field_name=name,
            event_type="update",
            deleted=0,
            version=version,
            payload=out.model_dump(),
        )
        return out
    finally:
        await _release_name_lock(session, ctx, name)


async def delete_soft(session: AsyncSession, ctx: RequestContext, name: str) -> None:
    rows = await session.execute(
        select(MemoryField).where(
            MemoryField.tenant_id == ctx.tenant_id,
            MemoryField.org_id == ctx.org_id,
            MemoryField.name == name,
            MemoryField.deleted == 0,
        )
    )
    items = list(rows.scalars().all())
    if not items:
        raise NotFoundError(f"memory_field '{name}' not found")

    for item in items:
        item.deleted = 1
        item.updated_by = ctx.user_id

    await session.commit()
    payload: dict[str, Any] = {"name": name, "deleted": 1}
    await schema_sync.publish_memory_field_change(
        tenant_id=ctx.tenant_id,
        org_id=ctx.org_id,
        memory_field_name=name,
        event_type="delete",
        deleted=1,
        payload=payload,
    )
