"""Mongo persistence for P0/P1 source events, atomic claims, and bundle audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from memory_engine.integrations.mongo_store import get_db

_indexes_ready = False
_index_lock = asyncio.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def namespace_key(namespace: dict[str, Any]) -> str:
    return f"{namespace['type']}:{namespace['id']}"


def claim_identity_id(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    dimension: str,
    claim_key: str,
) -> str:
    raw = ":".join(
        [
            str(tenant_id),
            str(org_id),
            user_id,
            namespace_key(namespace),
            dimension,
            claim_key,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def values_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, default=str
    )


def public_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Remove Mongo driver-only values before returning documents through APIs."""
    return {key: value for key, value in doc.items() if key != "_id"}


async def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    async with _index_lock:
        if _indexes_ready:
            return
        db = await get_db()
        await db.memory_source_event.create_index(
            [("tenant_id", ASCENDING), ("org_id", ASCENDING), ("event_id", ASCENDING)],
            unique=True,
            name="uk_source_event",
        )
        await db.memory_claim.create_index(
            [("tenant_id", ASCENDING), ("org_id", ASCENDING), ("claim_id", ASCENDING)],
            unique=True,
            name="uk_claim_id",
        )
        await db.memory_claim.create_index(
            [("identity_id", ASCENDING), ("revision", DESCENDING)],
            unique=True,
            name="uk_claim_revision",
        )
        await db.memory_claim.create_index(
            [("identity_id", ASCENDING), ("is_current", ASCENDING)],
            unique=True,
            partialFilterExpression={"is_current": True, "deleted": 0},
            name="uk_current_claim",
        )
        await db.memory_claim.create_index(
            [
                ("tenant_id", ASCENDING),
                ("org_id", ASCENDING),
                ("user_id", ASCENDING),
                ("namespace.type", ASCENDING),
                ("namespace.id", ASCENDING),
                ("is_current", ASCENDING),
                ("lifecycle_status", ASCENDING),
                ("dimension", ASCENDING),
            ],
            name="idx_claim_retrieve",
        )
        await db.memory_claim.create_index(
            [
                ("tenant_id", ASCENDING),
                ("org_id", ASCENDING),
                ("user_id", ASCENDING),
                ("namespace.type", ASCENDING),
                ("namespace.id", ASCENDING),
                ("provenance.source_id", ASCENDING),
                ("provenance.meeting_id", ASCENDING),
            ],
            name="idx_claim_evidence_neighbors",
        )
        await db.memory_bundle_audit.create_index(
            [("tenant_id", ASCENDING), ("org_id", ASCENDING), ("bundle_id", ASCENDING)],
            unique=True,
            name="uk_bundle_id",
        )
        await db.memory_bundle_audit.create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_bundle"
        )
        _indexes_ready = True


async def save_source_event(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    event: dict[str, Any],
) -> str:
    await ensure_indexes()
    db = await get_db()
    event_id = event.get("event_id") or f"mse_{uuid4().hex}"
    doc = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace": namespace,
        "event_id": event_id,
        **{k: v for k, v in event.items() if v is not None and k != "event_id"},
        "created_at": utc_now(),
    }
    await db.memory_source_event.update_one(
        {"tenant_id": tenant_id, "org_id": org_id, "event_id": event_id},
        {"$setOnInsert": doc},
        upsert=True,
    )
    return event_id


async def get_latest_claim(identity_id: str) -> dict[str, Any] | None:
    await ensure_indexes()
    db = await get_db()
    return await db.memory_claim.find_one(
        {"identity_id": identity_id, "is_current": True}, sort=[("revision", DESCENDING)]
    )


async def allocate_revision(identity_id: str) -> int:
    await ensure_indexes()
    db = await get_db()
    head = await db.memory_claim_head.find_one_and_update(
        {"_id": identity_id},
        {"$inc": {"revision": 1}, "$setOnInsert": {"created_at": utc_now()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(head["revision"])


async def insert_claim(doc: dict[str, Any], *, make_current: bool) -> dict[str, Any]:
    await ensure_indexes()
    db = await get_db()
    identity_id = doc["identity_id"]
    if make_current:
        await db.memory_claim.update_many(
            {"identity_id": identity_id, "is_current": True},
            {"$set": {"is_current": False, "updated_at": utc_now()}},
        )
    stored = {
        **doc,
        "claim_id": doc.get("claim_id") or f"mc_{uuid4().hex}",
        "revision": await allocate_revision(identity_id),
        "is_current": make_current,
        "deleted": 0,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await db.memory_claim.insert_one(stored)
    return stored


async def confirm_claim(
    claim_id: str, provenance: dict[str, Any], confidence: float
) -> dict[str, Any] | None:
    await ensure_indexes()
    db = await get_db()
    return await db.memory_claim.find_one_and_update(
        {"claim_id": claim_id, "deleted": 0},
        {
            "$addToSet": {"provenance": provenance},
            "$max": {"confidence": confidence},
            "$set": {"updated_at": utc_now()},
        },
        return_document=ReturnDocument.AFTER,
    )


async def mark_claim_status(claim_id: str, status: str, **extra: Any) -> None:
    await ensure_indexes()
    db = await get_db()
    await db.memory_claim.update_one(
        {"claim_id": claim_id, "deleted": 0},
        {"$set": {"lifecycle_status": status, "updated_at": utc_now(), **extra}},
    )


async def list_current_claims(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    *,
    dimensions: list[str] | None = None,
    limit: int = 200,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    await ensure_indexes()
    db = await get_db()
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace.type": namespace["type"],
        "namespace.id": namespace["id"],
        "deleted": 0,
    }
    if include_history:
        query["lifecycle_status"] = {"$in": ["active", "superseded", "conflicted"]}
    else:
        query["is_current"] = True
        query["lifecycle_status"] = "active"
    if dimensions:
        query["dimension"] = {"$in": dimensions}
    return await db.memory_claim.find(query).sort("updated_at", DESCENDING).limit(limit).to_list(limit)


async def list_current_claims_by_ids(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    claim_ids: list[str],
    *,
    dimensions: list[str] | None = None,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    """Return active claims selected by an external recall index.

    Semantic vector search is global within a user's namespace, whereas the
    regular candidate query is intentionally bounded for predictable Mongo
    work.  This helper lets retrieval hydrate Qdrant hits that fall outside
    that recency-bounded Mongo window without weakening tenant, user, or
    namespace isolation.
    """
    if not claim_ids:
        return []
    await ensure_indexes()
    db = await get_db()
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace.type": namespace["type"],
        "namespace.id": namespace["id"],
        "claim_id": {"$in": list(dict.fromkeys(claim_ids))},
        "deleted": 0,
    }
    if include_history:
        query["lifecycle_status"] = {"$in": ["active", "superseded", "conflicted"]}
    else:
        query["is_current"] = True
        query["lifecycle_status"] = "active"
    if dimensions:
        query["dimension"] = {"$in": dimensions}
    return await db.memory_claim.find(query).to_list(len(claim_ids))


async def list_current_claims_matching_phrases(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    phrases: list[str],
    *,
    dimensions: list[str] | None = None,
    limit: int = 40,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    """Recall active claims with one of the supplied literal text phrases.

    This is intentionally a narrow, user-scoped lexical fallback for compound
    action questions. It does not search across users or relax any lifecycle
    filter; policy filtering still happens in the retrieval service.
    """
    normalized = list(dict.fromkeys(p.strip() for p in phrases if p and p.strip()))
    if not normalized:
        return []
    await ensure_indexes()
    db = await get_db()
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace.type": namespace["type"],
        "namespace.id": namespace["id"],
        "deleted": 0,
        "$or": [
            {"text": {"$regex": re.escape(phrase), "$options": "i"}}
            for phrase in normalized
        ],
    }
    if include_history:
        query["lifecycle_status"] = {"$in": ["active", "superseded", "conflicted"]}
    else:
        query["is_current"] = True
        query["lifecycle_status"] = "active"
    if dimensions:
        query["dimension"] = {"$in": dimensions}
    return await db.memory_claim.find(query).sort("updated_at", DESCENDING).limit(limit).to_list(limit)


async def list_current_claims_matching_terms(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    terms: list[str],
    *,
    dimensions: list[str] | None = None,
    limit: int = 80,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    """Recall claims containing one of a bounded set of normalized query terms.

    The query remains tenant/user/namespace scoped. A word-prefix pattern
    covers simple English inflections (``project``/``projects``) without
    accepting caller-provided regular expressions.
    """
    normalized = list(dict.fromkeys(term.strip().lower() for term in terms if term and term.strip()))
    if not normalized:
        return []
    await ensure_indexes()
    db = await get_db()
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace.type": namespace["type"],
        "namespace.id": namespace["id"],
        "deleted": 0,
        "$or": [
            {"text": {"$regex": rf"\b{re.escape(term)}\w*\b", "$options": "i"}}
            for term in normalized
        ],
    }
    if include_history:
        query["lifecycle_status"] = {"$in": ["active", "superseded", "conflicted"]}
    else:
        query["is_current"] = True
        query["lifecycle_status"] = "active"
    if dimensions:
        query["dimension"] = {"$in": dimensions}
    return await db.memory_claim.find(query).sort("updated_at", DESCENDING).limit(limit).to_list(limit)


async def list_current_claim_evidence_neighbors(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    seed_claims: list[dict[str, Any]],
    *,
    dimensions: list[str] | None = None,
    limit: int = 16,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    """Return bounded same-session/source evidence for already-ranked seeds.

    We deliberately use only persisted provenance identifiers and retain the
    normal tenant/user/namespace/lifecycle filters.  ``source_id`` is the
    primary grouping key; ``meeting_id`` supports clients that model a whole
    meeting as multiple source events.  If neither exists this is a no-op.
    """
    source_ids: set[str] = set()
    meeting_ids: set[str] = set()
    seed_ids: set[str] = set()
    for claim in seed_claims:
        if claim.get("claim_id"):
            seed_ids.add(str(claim["claim_id"]))
        for provenance in claim.get("provenance") or []:
            if provenance.get("source_id"):
                source_ids.add(str(provenance["source_id"]))
            if provenance.get("meeting_id"):
                meeting_ids.add(str(provenance["meeting_id"]))
    clauses: list[dict[str, Any]] = []
    if source_ids:
        clauses.append({"provenance.source_id": {"$in": sorted(source_ids)}})
    if meeting_ids:
        clauses.append({"provenance.meeting_id": {"$in": sorted(meeting_ids)}})
    if not clauses:
        return []
    await ensure_indexes()
    db = await get_db()
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "org_id": org_id,
        "user_id": user_id,
        "namespace.type": namespace["type"],
        "namespace.id": namespace["id"],
        "deleted": 0,
        "claim_id": {"$nin": sorted(seed_ids)},
        "$or": clauses,
    }
    if include_history:
        query["lifecycle_status"] = {"$in": ["active", "superseded", "conflicted"]}
    else:
        query["is_current"] = True
        query["lifecycle_status"] = "active"
    if dimensions:
        query["dimension"] = {"$in": dimensions}
    return await db.memory_claim.find(query).sort("updated_at", DESCENDING).limit(limit).to_list(limit)


async def get_claim(
    tenant_id: int, org_id: int, claim_id: str
) -> dict[str, Any] | None:
    await ensure_indexes()
    db = await get_db()
    return await db.memory_claim.find_one(
        {"tenant_id": tenant_id, "org_id": org_id, "claim_id": claim_id, "deleted": 0}
    )


async def list_history(
    tenant_id: int, org_id: int, claim_id: str
) -> tuple[str, list[dict[str, Any]]] | None:
    claim = await get_claim(tenant_id, org_id, claim_id)
    if not claim:
        return None
    db = await get_db()
    items = await db.memory_claim.find(
        {"tenant_id": tenant_id, "org_id": org_id, "identity_id": claim["identity_id"]}
    ).sort("revision", DESCENDING).to_list(500)
    return claim["identity_id"], [public_document(item) for item in items]


async def save_bundle(doc: dict[str, Any]) -> dict[str, Any]:
    await ensure_indexes()
    db = await get_db()
    await db.memory_bundle_audit.insert_one(doc)
    return doc


async def get_bundle(
    tenant_id: int, org_id: int, bundle_id: str
) -> dict[str, Any] | None:
    await ensure_indexes()
    db = await get_db()
    return await db.memory_bundle_audit.find_one(
        {"tenant_id": tenant_id, "org_id": org_id, "bundle_id": bundle_id}
    )
