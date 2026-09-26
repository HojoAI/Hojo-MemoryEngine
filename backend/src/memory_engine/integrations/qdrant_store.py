"""Qdrant vector index for memory data."""

from __future__ import annotations

import logging
import hashlib
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from memory_engine.config import get_settings
from memory_engine.integrations.llm_client import embed_text, embed_texts

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None
_circuit_open_until: float = 0.0
_payload_indexes_ready: set[str] = set()

# These fields are present in every claim vector payload and are used by the
# semantic retrieval filter.  Without payload indexes Qdrant may fall back to
# scanning a large collection; behind the canal HTTPS gateway that can surface
# as a 502/timeout even though unfiltered vector queries work.
_CLAIM_PAYLOAD_INDEXES: dict[str, qmodels.PayloadSchemaType] = {
    "record_type": qmodels.PayloadSchemaType.KEYWORD,
    "org_id": qmodels.PayloadSchemaType.INTEGER,
    "user_id": qmodels.PayloadSchemaType.KEYWORD,
    "session_id": qmodels.PayloadSchemaType.KEYWORD,
    "namespace_type": qmodels.PayloadSchemaType.KEYWORD,
    "namespace_id": qmodels.PayloadSchemaType.KEYWORD,
    "lifecycle_status": qmodels.PayloadSchemaType.KEYWORD,
    "deleted": qmodels.PayloadSchemaType.INTEGER,
    "dimension": qmodels.PayloadSchemaType.KEYWORD,
}


def _stable_point_id(value: str) -> int:
    """Map an external id to a stable positive Qdrant integer id."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & (2**63 - 1)


def collection_name(tenant_id: int) -> str:
    return f"memory_vectors_{tenant_id}"


def _format_qdrant_error(exc: BaseException) -> str:
    """Human-readable Qdrant error for logs."""
    name = type(exc).__name__
    message = str(exc).strip()
    if message:
        return f"{name}: {message}"
    return name


def _record_qdrant_failure(exc: BaseException) -> None:
    """Open circuit breaker after transport/auth failures."""
    global _circuit_open_until
    settings = get_settings()
    _circuit_open_until = time.monotonic() + settings.qdrant_circuit_breaker_seconds
    logger.warning(
        "qdrant unavailable (%s); circuit open for %.0fs url=%s",
        _format_qdrant_error(exc),
        settings.qdrant_circuit_breaker_seconds,
        get_settings().qdrant_startup_diag(),
    )


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def qdrant_is_available() -> bool:
    """Whether Qdrant calls should be attempted (config + circuit breaker)."""
    settings = get_settings()
    if not settings.qdrant_url:
        return False
    return not _circuit_is_open()


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        settings = get_settings()
        parsed = urlparse(settings.qdrant_url)
        scheme = parsed.scheme or "http"
        # urlparse("qdrant.hojoai.com") => hostname=None, path="qdrant.hojoai.com"
        host = parsed.hostname or parsed.path
        if not host:
            raise ValueError("Invalid QDRANT_URL (missing host)")

        # Qdrant REST defaults to 6333, but your deployment uses HTTPS gateway on 443.
        # Explicitly set port to avoid qdrant_client defaulting to 6333.
        port = parsed.port or (443 if scheme == "https" else 80)
        prefix = parsed.path or ""
        prefix = prefix.strip("/")
        kwargs: dict[str, Any] = {
            "location": host,
            "port": port,
            "https": scheme == "https",
            "check_compatibility": False,
            "timeout": settings.qdrant_timeout_seconds,
        }
        if prefix:
            kwargs["prefix"] = prefix
        if settings.qdrant_api_key:
            kwargs["api_key"] = settings.qdrant_api_key
        _client = AsyncQdrantClient(**kwargs)
    return _client


async def ping_qdrant(*, record_failure: bool = True) -> tuple[bool, str]:
    """Return ``(ok, detail)`` for startup/health checks."""
    settings = get_settings()
    if not settings.qdrant_url:
        return False, "QDRANT_URL is empty"
    if _circuit_is_open():
        return False, "circuit breaker open"
    try:
        client = await get_client()
        await client.get_collections()
        return True, ""
    except Exception as exc:
        if record_failure:
            _record_qdrant_failure(exc)
        return False, _format_qdrant_error(exc)


async def _list_collection_names(client: AsyncQdrantClient) -> set[str] | None:
    """Return Qdrant collection names, or None when the service is unreachable."""
    if not qdrant_is_available():
        return None
    try:
        collections = await client.get_collections()
        return {c.name for c in collections.collections}
    except UnexpectedResponse as exc:
        _record_qdrant_failure(exc)
        logger.warning("qdrant get_collections failed: %s", _format_qdrant_error(exc))
        return None
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
        _record_qdrant_failure(exc)
        logger.warning("qdrant get_collections failed: %s", _format_qdrant_error(exc))
        return None
    except Exception as exc:
        _record_qdrant_failure(exc)
        logger.warning("qdrant get_collections failed: %s", _format_qdrant_error(exc))
        return None


async def ensure_collection(tenant_id: int, vector_size: int = 1536) -> bool:
    """Create collection and claim payload indexes if missing."""
    if not qdrant_is_available():
        return False
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None:
        return False
    if name not in existing:
        await client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )
    await ensure_payload_indexes(client, name)
    return True


async def ensure_payload_indexes(
    client: AsyncQdrantClient,
    collection: str,
) -> bool:
    """Ensure the claim filter fields have Qdrant payload indexes.

    Index creation is idempotent and intentionally best-effort: a temporary
    gateway failure must not prevent Mongo-backed memory writes.  The next
    request retries until every index is visible in the collection schema.
    ``wait=False`` avoids blocking the API request while Qdrant builds an
    index over an existing large collection.
    """
    if collection in _payload_indexes_ready:
        return True
    try:
        info = await client.get_collection(collection)
        payload_schema = getattr(info, "payload_schema", None) or {}
    except Exception as exc:
        logger.warning(
            "qdrant payload index inspection failed collection=%s: %s",
            collection,
            _format_qdrant_error(exc),
        )
        return False

    all_ready = True
    for field_name, field_schema in _CLAIM_PAYLOAD_INDEXES.items():
        if field_name in payload_schema:
            continue
        try:
            await client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=field_schema,
                wait=False,
            )
            logger.info(
                "qdrant payload index requested collection=%s field=%s schema=%s",
                collection,
                field_name,
                field_schema,
            )
        except Exception as exc:
            all_ready = False
            logger.warning(
                "qdrant payload index creation failed collection=%s field=%s: %s",
                collection,
                field_name,
                _format_qdrant_error(exc),
            )

    if all_ready:
        _payload_indexes_ready.add(collection)
    return all_ready


async def upsert_vector(
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    mongo_id: str,
    text: str,
) -> None:
    """Index text embedding (async index path)."""
    if not await ensure_collection(tenant_id):
        raise RuntimeError("qdrant unavailable")
    client = await get_client()
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


async def upsert_claim_vector(claim: dict[str, Any]) -> None:
    """Index one atomic Memory Claim with metadata required for hard filtering."""
    tenant_id = int(claim["tenant_id"])
    if not await ensure_collection(tenant_id):
        raise RuntimeError("qdrant unavailable")
    client = await get_client()
    text = str(claim.get("text") or claim.get("value") or "").strip()
    if not text:
        return
    vector = await embed_text(text)
    claim_id = str(claim["claim_id"])
    point_id = _stable_point_id(f"claim:{claim_id}")
    policy = claim.get("access_policy") or {}
    namespace = claim.get("namespace") or {}
    await client.upsert(
        collection_name=collection_name(tenant_id),
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "record_type": "memory_claim",
                    "claim_id": claim_id,
                    "org_id": claim["org_id"],
                    "user_id": claim["user_id"],
                    "namespace_type": namespace.get("type"),
                    "namespace_id": namespace.get("id"),
                    "dimension": claim.get("dimension"),
                    "lifecycle_status": claim.get("lifecycle_status"),
                    "allowed_modules": policy.get("allowed_modules", ["*"]),
                    "allowed_scopes": policy.get("allowed_scopes", ["self"]),
                    "deleted": 0,
                },
            )
        ],
    )


async def upsert_aml_memory_units(units: list[dict[str, Any]]) -> None:
    """Synchronously index AML evidence units as one batch."""
    if not units:
        return
    tenant_ids = {int(unit["tenant_id"]) for unit in units}
    if len(tenant_ids) != 1:
        raise ValueError("AML vector batch must belong to one tenant")
    tenant_id = tenant_ids.pop()
    if not await ensure_collection(tenant_id):
        raise RuntimeError("qdrant unavailable")
    texts = [str(unit["searchable_content"]) for unit in units]
    vectors = await embed_texts(texts)
    if len(vectors) != len(units):
        raise RuntimeError("embedding provider returned an incomplete AML batch")
    client = await get_client()
    await client.upsert(
        collection_name=collection_name(tenant_id),
        points=[
            qmodels.PointStruct(
                id=_stable_point_id(f"aml:{unit['unit_id']}"),
                vector=vector,
                payload={
                    "record_type": "aml_memory",
                    "unit_id": unit["unit_id"],
                    "org_id": unit["org_id"],
                    "user_id": unit["user_id"],
                    "session_id": unit["session_id"],
                    "deleted": 0,
                },
            )
            for unit, vector in zip(units, vectors, strict=True)
        ],
        wait=True,
    )


async def search_aml_memory_units(
    tenant_id: int,
    org_id: int,
    user_id: str,
    query_text: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Semantic AML recall with a mandatory user partition filter."""
    if not query_text.strip() or not qdrant_is_available():
        return []
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return []
    response = await client.query_points(
        collection_name=name,
        query=await embed_text(query_text),
        query_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="record_type", match=qmodels.MatchValue(value="aml_memory")
                ),
                qmodels.FieldCondition(key="org_id", match=qmodels.MatchValue(value=org_id)),
                qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)),
                qmodels.FieldCondition(key="deleted", match=qmodels.MatchValue(value=0)),
            ]
        ),
        limit=limit,
    )
    return [
        {"unit_id": (point.payload or {}).get("unit_id"), "score": float(point.score)}
        for point in response.points
        if (point.payload or {}).get("unit_id")
    ]


async def delete_aml_memory_for_user(tenant_id: int, org_id: int, user_id: str) -> None:
    """Physically delete AML vectors for one evaluation user partition."""
    if not qdrant_is_available():
        raise RuntimeError("qdrant unavailable during AML cleanup")
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return
    await client.delete(
        collection_name=name,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="record_type", match=qmodels.MatchValue(value="aml_memory")
                    ),
                    qmodels.FieldCondition(
                        key="org_id", match=qmodels.MatchValue(value=org_id)
                    ),
                    qmodels.FieldCondition(
                        key="user_id", match=qmodels.MatchValue(value=user_id)
                    ),
                ]
            )
        ),
        wait=True,
    )


async def search_claim_vectors(
    tenant_id: int,
    org_id: int,
    user_id: str,
    namespace: dict[str, Any],
    query_text: str,
    *,
    dimensions: list[str] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Semantic candidate recall with mandatory user and namespace isolation."""
    if not query_text.strip() or not qdrant_is_available():
        return []
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return []
    must: list[qmodels.FieldCondition] = [
        qmodels.FieldCondition(key="record_type", match=qmodels.MatchValue(value="memory_claim")),
        qmodels.FieldCondition(key="org_id", match=qmodels.MatchValue(value=org_id)),
        qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)),
        qmodels.FieldCondition(
            key="namespace_type", match=qmodels.MatchValue(value=namespace["type"])
        ),
        qmodels.FieldCondition(
            key="namespace_id", match=qmodels.MatchValue(value=namespace["id"])
        ),
        qmodels.FieldCondition(
            key="lifecycle_status", match=qmodels.MatchValue(value="active")
        ),
        qmodels.FieldCondition(key="deleted", match=qmodels.MatchValue(value=0)),
    ]
    if dimensions:
        must.append(
            qmodels.FieldCondition(key="dimension", match=qmodels.MatchAny(any=dimensions))
        )
    hits = await client.search(
        collection_name=name,
        query_vector=await embed_text(query_text),
        query_filter=qmodels.Filter(must=must),
        limit=limit,
    )
    return [
        {"claim_id": (hit.payload or {}).get("claim_id"), "score": float(hit.score)}
        for hit in hits
        if (hit.payload or {}).get("claim_id")
    ]


async def mark_claim_deleted(tenant_id: int, claim_id: str) -> None:
    if not qdrant_is_available():
        return
    client = await get_client()
    name = collection_name(tenant_id)
    existing = await _list_collection_names(client)
    if existing is None or name not in existing:
        return
    await client.set_payload(
        collection_name=name,
        payload={"deleted": 1},
        points=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="claim_id", match=qmodels.MatchValue(value=claim_id)
                )
            ]
        ),
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
    if not qdrant_is_available():
        return []
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
    if not qdrant_is_available():
        return
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
    if not qdrant_is_available():
        return 0
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
            # qdrant-client 1.18 accepts the selector through ``points``.
            # ``points_selector`` was accepted by an older client surface and
            # silently left vectors live here after it became incompatible.
            points=qmodels.FilterSelector(filter=filt),
        )
        return marked
    except UnexpectedResponse as exc:
        logger.warning("qdrant mark_vectors_deleted_for_user failed: %s", _format_qdrant_error(exc))
        return 0
    except Exception as exc:
        logger.warning("qdrant mark_vectors_deleted_for_user failed: %s", _format_qdrant_error(exc))
        return 0
