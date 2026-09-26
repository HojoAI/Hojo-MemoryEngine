"""MongoDB memory data store."""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument

from memory_engine.config import get_settings
from memory_engine.constants.user_memory_item import (
    KB_MEMORY_FIELDS,
    MEETING_MEMORY_FIELDS,
    MEMORY_FIELD_TO_DIMENSION,
    SCHEDULE_MEMORY_FIELDS,
    MemorySourceType,
)

_client: AsyncIOMotorClient | None = None


def _doc_id(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    source: str | None = None,
) -> str:
    raw = f"{tenant_id}:{org_id}:{user_id}:{memory_field_name}"
    # Non-empty source gets its own door; None/empty keeps legacy id (no source suffix).
    if source:
        raw = f"{raw}:{source}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_db() -> AsyncIOMotorDatabase:
    """Mongo database handle."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongodb_dsn)
    return _client[get_settings().mongodb_database]


_SOURCE_UNSET: Any = object()


async def get_memory_data(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    source: str | None | Any = _SOURCE_UNSET,
) -> dict[str, Any] | None:
    """Fetch one memory data document.

    Omit ``source`` to skip source filtering. Pass ``source=None`` to match
    docs with missing/null source.
    """
    db = await get_db()
    query: dict[str, Any] = {
        "_id": _doc_id(
            tenant_id,
            org_id,
            user_id,
            memory_field_name,
            source=None if source is _SOURCE_UNSET else source,
        ),
        "deleted": 0,
    }
    doc = await db.memory_data.find_one(query)
    return doc


async def upsert_memory_data(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    value: Any,
    *,
    match_method: str = "OVERWRITE",
    source: str | None = None,
    original_expression: str | None = None,
) -> dict[str, Any]:
    """Upsert memory data with OVERWRITE/APPEND/MERGE (MERGE fusion is applied upstream)."""
    db = await get_db()
    doc_id = _doc_id(tenant_id, org_id, user_id, memory_field_name, source=source)
    # None matches both missing and null source fields in MongoDB.
    existing = await db.memory_data.find_one({"_id": doc_id})
    now = datetime.now(timezone.utc).isoformat()

    if existing is None or existing.get("deleted") == 1:
        new_value = value
    elif match_method == "APPEND":
        old = existing.get("value")
        if isinstance(old, list):
            new_value = old + (value if isinstance(value, list) else [value])
        else:
            new_value = [old, value]
    else:
        # MERGE fusion is handled in memory_data service (LLM via merge_rule) before upsert.
        new_value = value

    doc: dict[str, Any] = {
        "_id": doc_id,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "memory_field_name": memory_field_name,
        "value": new_value,
        "deleted": 0,
        "updated_at": now,
    }
    if source is not None:
        doc["source"] = source
    # elif existing is not None and existing.get("source"):
    #     doc["source"] = existing["source"]

    if existing is None or existing.get("deleted") == 1:
        doc["create_time"] = now
    else:
        if existing.get("create_time"):
            doc["create_time"] = existing["create_time"]
        if existing.get("recently_used"):
            doc["recently_used"] = existing["recently_used"]

    if original_expression is not None and str(original_expression).strip():
        doc["original_expression"] = str(original_expression).strip()
    elif existing is not None and existing.get("original_expression"):
        doc["original_expression"] = existing["original_expression"]

    await db.memory_data.replace_one({"_id": doc_id}, doc, upsert=True)
    return doc


async def mark_memory_data_recently_used(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    recently_used: str,
    memory_field_names: list[str] | None = None,
    item_ids: list[str] | None = None,
) -> int:
    """Set ``recently_used`` on matching non-deleted memory_data documents."""
    db = await get_db()
    clauses: list[dict[str, Any]] = []
    names = [n.strip() for n in (memory_field_names or []) if n and n.strip()]
    ids = [i.strip() for i in (item_ids or []) if i and i.strip()]
    if names:
        clauses.append(
            {
                "tenant_id": tenant_id,
                "org_id": org_id,
                "user_id": user_id,
                "deleted": 0,
                "memory_field_name": {"$in": names},
            }
        )
    if ids:
        clauses.append(
            {
                "tenant_id": tenant_id,
                "org_id": org_id,
                "user_id": user_id,
                "deleted": 0,
                "_id": {"$in": ids},
            }
        )
    if not clauses:
        return 0
    query: dict[str, Any] = clauses[0] if len(clauses) == 1 else {"$or": clauses}
    # Do not bump updated_at — detail 「时间」 stays content write time.
    result = await db.memory_data.update_many(
        query,
        {"$set": {"recently_used": recently_used}},
    )
    return int(result.modified_count)


def _memory_data_user_query(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    memory_field_name: str | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "deleted": 0,
    }
    if memory_field_name:
        query["memory_field_name"] = memory_field_name
    return query


def _user_id_substring_filter(user_id: str | None) -> dict[str, Any]:
    """Build a MongoDB substring filter for ``user_id`` (partial match)."""
    needle = (user_id or "").strip()
    if not needle:
        return {}
    return {"user_id": {"$regex": re.escape(needle)}}


def _memory_data_tenant_query(
    tenant_id: int,
    org_id: int,
    *,
    memory_field_name: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Active memory docs scoped to tenant + org (all partitions)."""
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "deleted": 0,
    }
    query.update(_user_id_substring_filter(user_id))
    if memory_field_name:
        query["memory_field_name"] = memory_field_name
    return query


async def count_memory_data_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    memory_field_name: str | None = None,
) -> int:
    """Count active memory documents for a user."""
    db = await get_db()
    query = _memory_data_user_query(
        tenant_id, org_id, user_id, memory_field_name=memory_field_name
    )
    return await db.memory_data.count_documents(query)


async def has_memory_data_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
) -> bool:
    """Return whether the user has at least one active memory document."""
    db = await get_db()
    query = _memory_data_user_query(tenant_id, org_id, user_id)
    doc = await db.memory_data.find_one(query, {"_id": 1})
    return doc is not None


async def list_memory_data_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    memory_field_name: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List active memory documents for a user (implicit retrieve / debug list)."""
    db = await get_db()
    query = _memory_data_user_query(
        tenant_id, org_id, user_id, memory_field_name=memory_field_name
    )
    cursor = (
        db.memory_data.find(query)
        .sort("memory_field_name", 1)
        .skip(max(offset, 0))
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def count_memory_data_for_tenant(
    tenant_id: int,
    org_id: int,
    *,
    memory_field_name: str | None = None,
    user_id: str | None = None,
) -> int:
    """Count active memory documents for a tenant/org scope."""
    db = await get_db()
    query = _memory_data_tenant_query(
        tenant_id,
        org_id,
        memory_field_name=memory_field_name,
        user_id=user_id,
    )
    return await db.memory_data.count_documents(query)


async def list_memory_data_for_tenant(
    tenant_id: int,
    org_id: int,
    *,
    memory_field_name: str | None = None,
    user_id: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List active memory documents for all users under tenant/org."""
    db = await get_db()
    query = _memory_data_tenant_query(
        tenant_id,
        org_id,
        memory_field_name=memory_field_name,
        user_id=user_id,
    )
    cursor = (
        db.memory_data.find(query)
        .sort([("user_id", 1), ("memory_field_name", 1)])
        .skip(max(offset, 0))
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


def _dimension_filter_clause(dimension: str | None) -> dict[str, Any] | None:
    if not dimension or not dimension.strip():
        return None
    dim = dimension.strip().lower()
    mapped = [name for name, value in MEMORY_FIELD_TO_DIMENSION.items() if value == dim]
    if dim == "background":
        return {
            "$or": [
                {"memory_field_name": {"$in": mapped}},
                {"memory_field_name": {"$nin": list(MEMORY_FIELD_TO_DIMENSION.keys())}},
            ]
        }
    if not mapped:
        return {"memory_field_name": "__none__"}
    return {"memory_field_name": {"$in": mapped}}


def _source_filter_clause(source: str | None) -> dict[str, Any] | None:
    if not source or not source.strip():
        return None
    src = source.strip().lower()
    if src == MemorySourceType.KNOWLEDGE.value:
        return {
            "$or": [
                {"source": MemorySourceType.KNOWLEDGE.value},
                {
                    "$and": [
                        {"source": {"$exists": False}},
                        {"memory_field_name": {"$in": list(KB_MEMORY_FIELDS)}},
                    ]
                },
            ]
        }
    if src == MemorySourceType.SCHEDULE.value:
        return {
            "$or": [
                {"source": MemorySourceType.SCHEDULE.value},
                {
                    "$and": [
                        {"source": {"$exists": False}},
                        {"memory_field_name": {"$in": list(SCHEDULE_MEMORY_FIELDS)}},
                    ]
                },
            ]
        }
    if src == MemorySourceType.MEETING.value:
        return {
            "$or": [
                {"source": MemorySourceType.MEETING.value},
                {
                    "$and": [
                        {"source": {"$exists": False}},
                        {"memory_field_name": {"$in": list(MEETING_MEMORY_FIELDS)}},
                    ]
                },
            ]
        }
    if src == MemorySourceType.DIALOGUE.value:
        return {
            "$or": [
                {"source": MemorySourceType.DIALOGUE.value},
                {
                    "$and": [
                        {"source": {"$exists": False}},
                        {"memory_field_name": {"$nin": list(KB_MEMORY_FIELDS)}},
                        {"memory_field_name": {"$nin": list(SCHEDULE_MEMORY_FIELDS)}},
                        {"memory_field_name": {"$nin": list(MEETING_MEMORY_FIELDS)}},
                    ]
                },
            ]
        }
    return {"memory_field_name": "__none__"}


def _memory_data_user_list_query(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    dimension: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Build Mongo filter for H5 user list (memory_data granularity)."""
    base = _memory_data_user_query(tenant_id, org_id, user_id)
    clauses: list[dict[str, Any]] = [base]
    dim_clause = _dimension_filter_clause(dimension)
    if dim_clause:
        clauses.append(dim_clause)
    src_clause = _source_filter_clause(source)
    if src_clause:
        clauses.append(src_clause)
    if keyword and keyword.strip():
        needle = re.escape(keyword.strip())
        clauses.append(
            {
                "$or": [
                    {"memory_field_name": {"$regex": needle, "$options": "i"}},
                    {"value": {"$regex": needle, "$options": "i"}},
                ]
            }
        )
    time_filter: dict[str, str] = {}
    if start_time:
        time_filter["$gte"] = start_time
    if end_time:
        time_filter["$lte"] = end_time
    if time_filter:
        clauses.append({"updated_at": time_filter})
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _memory_data_sort_field(sort_field: str) -> str:
    allowed = {"updated_at", "memory_field_name", "create_time"}
    normalized = (sort_field or "updated_at").strip()
    return normalized if normalized in allowed else "updated_at"


async def count_memory_data_for_user_filtered(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    dimension: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> int:
    """Count active memory_data rows matching H5 list filters."""
    db = await get_db()
    query = _memory_data_user_list_query(
        tenant_id,
        org_id,
        user_id,
        dimension=dimension,
        source=source,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
    )
    return await db.memory_data.count_documents(query)


async def list_memory_data_for_user_filtered(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    dimension: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    offset: int = 0,
    limit: int = 20,
    sort_field: str = "updated_at",
    sort_desc: bool = True,
) -> list[dict[str, Any]]:
    """List active memory_data rows with H5 list filters."""
    db = await get_db()
    query = _memory_data_user_list_query(
        tenant_id,
        org_id,
        user_id,
        dimension=dimension,
        source=source,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
    )
    direction = -1 if sort_desc else 1
    mongo_field = _memory_data_sort_field(sort_field)
    cursor = (
        db.memory_data.find(query)
        .sort(mongo_field, direction)
        .skip(max(offset, 0))
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def get_memory_data_by_id(
    tenant_id: int,
    org_id: int,
    user_id: str,
    doc_id: str,
) -> dict[str, Any] | None:
    """Fetch one active memory_data document by ``_id``."""
    db = await get_db()
    return await db.memory_data.find_one(
        {
            "_id": doc_id,
            "tenant_id": tenant_id,
            "org_id": org_id,
            "user_id": user_id,
            "deleted": 0,
        }
    )


async def soft_delete_memory_data(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    source: str | None = None,
) -> bool:
    """Soft-delete memory data for one field (+ optional source)."""
    db = await get_db()
    result = await db.memory_data.update_one(
        {
            "_id": _doc_id(tenant_id, org_id, user_id, memory_field_name, source=source),
            "deleted": 0,
        },
        {"$set": {"deleted": 1, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return result.modified_count > 0


async def soft_delete_memory_data_by_id(
    tenant_id: int,
    org_id: int,
    user_id: str,
    doc_id: str,
) -> dict[str, Any] | None:
    """Soft-delete one active memory_data document by ``_id``; return prior doc or None."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    doc = await db.memory_data.find_one_and_update(
        {
            "_id": doc_id,
            "tenant_id": tenant_id,
            "org_id": org_id,
            "user_id": user_id,
            "deleted": 0,
        },
        {"$set": {"deleted": 1, "updated_at": now}},
        return_document=ReturnDocument.BEFORE,
    )
    return doc


async def update_memory_data_value_by_id(
    tenant_id: int,
    org_id: int,
    user_id: str,
    doc_id: str,
    value: Any,
    *,
    original_expression: str | None = None,
) -> dict[str, Any] | None:
    """Overwrite ``value`` on one active memory_data document by ``_id``."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    updates: dict[str, Any] = {"value": value, "updated_at": now, "deleted": 0}
    if original_expression is not None:
        updates["original_expression"] = original_expression
    result = await db.memory_data.find_one_and_update(
        {
            "_id": doc_id,
            "tenant_id": tenant_id,
            "org_id": org_id,
            "user_id": user_id,
            "deleted": 0,
        },
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    return result


async def soft_delete_all_memory_data_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
) -> int:
    """Mark ``deleted=1`` on active docs (retained in DB; list/get skip ``deleted=0`` only)."""
    db = await get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = await db.memory_data.update_many(
        _memory_data_user_query(tenant_id, org_id, user_id),
        {"$set": {"deleted": 1, "updated_at": now}},
    )
    return int(result.modified_count)
