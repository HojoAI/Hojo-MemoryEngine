"""Mongo persistence for AML raw evidence and idempotent Add requests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from memory_engine.integrations.mongo_store import get_db

_indexes_ready = False
_index_lock = asyncio.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    async with _index_lock:
        if _indexes_ready:
            return
        db = await get_db()
        await db.aml_add_request.create_index(
            [("tenant_id", ASCENDING), ("org_id", ASCENDING), ("request_id", ASCENDING)],
            unique=True,
            name="uk_aml_add_request",
        )
        await db.aml_memory_unit.create_index(
            [("tenant_id", ASCENDING), ("org_id", ASCENDING), ("unit_id", ASCENDING)],
            unique=True,
            name="uk_aml_memory_unit",
        )
        await db.aml_memory_unit.create_index(
            [
                ("tenant_id", ASCENDING),
                ("org_id", ASCENDING),
                ("user_id", ASCENDING),
                ("event_time_ms", DESCENDING),
            ],
            name="idx_aml_user_time",
        )
        _indexes_ready = True


async def get_add_request(
    tenant_id: int, org_id: int, request_id: str
) -> dict[str, Any] | None:
    await ensure_indexes()
    db = await get_db()
    return await db.aml_add_request.find_one(
        {"tenant_id": tenant_id, "org_id": org_id, "request_id": request_id}
    )


async def reserve_add_request(record: dict[str, Any]) -> dict[str, Any]:
    """Create the request ledger before writes so payload conflicts are rejected."""
    await ensure_indexes()
    db = await get_db()
    return await db.aml_add_request.find_one_and_update(
        {
            "tenant_id": record["tenant_id"],
            "org_id": record["org_id"],
            "request_id": record["request_id"],
        },
        {"$setOnInsert": record},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


async def upsert_units(units: list[dict[str, Any]]) -> None:
    if not units:
        return
    await ensure_indexes()
    db = await get_db()
    for unit in units:
        await db.aml_memory_unit.update_one(
            {
                "tenant_id": unit["tenant_id"],
                "org_id": unit["org_id"],
                "unit_id": unit["unit_id"],
            },
            {"$setOnInsert": unit},
            upsert=True,
        )


async def complete_add_request(
    tenant_id: int, org_id: int, request_id: str, payload_hash: str
) -> None:
    await ensure_indexes()
    db = await get_db()
    result = await db.aml_add_request.update_one(
        {
            "tenant_id": tenant_id,
            "org_id": org_id,
            "request_id": request_id,
            "payload_hash": payload_hash,
        },
        {"$set": {"status": "complete", "completed_at": utc_now()}},
    )
    if result.matched_count != 1:
        raise RuntimeError("AML request ledger changed during Add")


async def list_units_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    await ensure_indexes()
    db = await get_db()
    query = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
    }
    return (
        await db.aml_memory_unit.find(query)
        .sort([("event_time_ms", DESCENDING), ("created_at", DESCENDING)])
        .limit(limit)
        .to_list(limit)
    )


async def list_units_by_ids(
    tenant_id: int,
    org_id: int,
    user_id: str,
    unit_ids: list[str],
) -> list[dict[str, Any]]:
    if not unit_ids:
        return []
    await ensure_indexes()
    db = await get_db()
    query = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "unit_id": {"$in": unit_ids},
    }
    return await db.aml_memory_unit.find(query).to_list(len(unit_ids))


async def delete_user_data(tenant_id: int, org_id: int, user_id: str) -> tuple[int, int]:
    await ensure_indexes()
    db = await get_db()
    scope = {"tenant_id": tenant_id, "org_id": org_id, "user_id": user_id}
    units = await db.aml_memory_unit.delete_many(scope)
    requests = await db.aml_add_request.delete_many(scope)
    return int(units.deleted_count), int(requests.deleted_count)


async def ping() -> bool:
    db = await get_db()
    await db.command("ping")
    return True
