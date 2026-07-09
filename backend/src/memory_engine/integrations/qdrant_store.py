"""Qdrant vector index for memory data."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from memory_engine.config import get_settings
from memory_engine.integrations.llm_client import embed_text

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


def collection_name(tenant_id: int) -> str:
    return f"memory_vectors_{tenant_id}"


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=get_settings().qdrant_url,
            check_compatibility=False,
        )
    return _client


async def _list_collection_names(client: AsyncQdrantClient) -> set[str] | None:
    """Return Qdrant collection names, or None when the service is unreachable."""
    try:
        collections = await client.get_collections()
        return {c.name for c in collections.collections}
    except UnexpectedResponse as exc:
        logger.warning("qdrant get_collections failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("qdrant get_collections failed: %s", exc)
        return None


async def ensure_collection(tenant_id: int, vector_size: int = 1536) -> None:
    """Create collection if missing."""
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None:
        return
    if name not in existing:
        await client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )


async def upsert_vector(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    mongo_id: str,
    text: str,
) -> None:
    """Index text embedding (async index path)."""
    client = await get_client()
    await ensure_collection(tenant_id)
    vector = await embed_text(text)
    point_id = abs(hash(f"{mongo_id}:{memory_field_name}")) % (2**63 - 1)
    await client.upsert(
        collection_name=collection_name(tenant_id),
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "org_id": org_id,
                    "user_id": user_id,
                    "memory_field_name": memory_field_name,
                    "mongo_id": mongo_id,
                    "deleted": 0,
                },
            )
        ],
    )


async def search_vectors(
    tenant_id: int,
    org_id: int,
    user_id: str,
    query_text: str,
    *,
    memory_field_name: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Semantic search over indexed memory vectors for a user."""
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return []

    vector = await embed_text(query_text)
    must: list[qmodels.FieldCondition] = [
        qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)),
        qmodels.FieldCondition(key="org_id", match=qmodels.MatchValue(value=org_id)),
        qmodels.FieldCondition(key="deleted", match=qmodels.MatchValue(value=0)),
    ]
    if memory_field_name:
        must.append(
            qmodels.FieldCondition(
                key="memory_field_name",
                match=qmodels.MatchValue(value=memory_field_name),
            )
        )

    hits = await client.search(
        collection_name=name,
        query_vector=vector,
        query_filter=qmodels.Filter(must=must),
        limit=limit,
    )
    results: list[dict[str, Any]] = []
    for hit in hits:
        payload = hit.payload or {}
        results.append(
            {
                "score": hit.score,
                "memory_field_name": payload.get("memory_field_name"),
                "mongo_id": payload.get("mongo_id"),
            }
        )
    return results


async def mark_deleted(tenant_id: int, mongo_id: str, memory_field_name: str) -> None:
    """Mark vector payload deleted."""
    client = await get_client()
    point_id = abs(hash(f"{mongo_id}:{memory_field_name}")) % (2**63 - 1)
    await client.set_payload(
        collection_name=collection_name(tenant_id),
        payload={"deleted": 1},
        points=[point_id],
    )


def _user_vector_markable_filter(org_id: int, user_id: str) -> qmodels.Filter:
    """Vectors for a partition that are not yet marked deleted (incl. missing ``deleted``)."""
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="user_id",
                match=qmodels.MatchValue(value=user_id),
            ),
            qmodels.FieldCondition(
                key="org_id",
                match=qmodels.MatchValue(value=org_id),
            ),
        ],
        must_not=[
            qmodels.FieldCondition(key="deleted", match=qmodels.MatchValue(value=1)),
        ],
    )


async def mark_vectors_deleted_for_user(
    tenant_id: int,
    org_id: int,
    user_id: str,
) -> int:
    """Soft-delete Qdrant vectors (``payload.deleted=1``); does not remove points."""
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return 0
    filt = _user_vector_markable_filter(org_id, user_id)
    try:
        marked = 0
        offset = None
        while True:
            records, offset = await client.scroll(
                collection_name=name,
                scroll_filter=filt,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            marked += len(records)
            if offset is None:
                break
        if marked == 0:
            return 0
        await client.set_payload(
            collection_name=name,
            payload={"deleted": 1},
            points_selector=qmodels.FilterSelector(filter=filt),
        )
        return marked
    except UnexpectedResponse as exc:
        logger.warning("qdrant mark_vectors_deleted_for_user failed: %s", exc)
        return 0
    except Exception as exc:
        logger.warning("qdrant mark_vectors_deleted_for_user failed: %s", exc)
        return 0
