"""Redis schema cache."""

import json
from typing import Any

import redis.asyncio as redis

from memory_engine.config import get_settings

_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Lazy Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        timeout_s = settings.redis_socket_timeout_ms / 1000.0
        _client = redis.from_url(
            settings.redis_dsn,
            decode_responses=True,
            socket_connect_timeout=timeout_s,
            socket_timeout=timeout_s,
        )
    return _client


def schema_key(tenant_id: int, org_id: int, name: str) -> str:
    """Active schema cache key."""
    return get_settings().redis_key("schema", str(tenant_id), str(org_id), name)


def schema_deleted_key(tenant_id: int, org_id: int, name: str) -> str:
    """Deleted-transition cache key."""
    return get_settings().redis_key("schema", str(tenant_id), str(org_id), name, "deleted")


async def set_schema_cache(tenant_id: int, org_id: int, name: str, payload: dict[str, Any]) -> None:
    """Cache active memory_field JSON."""
    r = await get_redis()
    await r.set(schema_key(tenant_id, org_id, name), json.dumps(payload, default=str))


async def set_schema_deleted_cache(
    tenant_id: int, org_id: int, name: str, payload: dict[str, Any], ttl: int = 300
) -> None:
    """Cache deleted marker with TTL."""
    r = await get_redis()
    data = {**payload, "deleted": 1}
    await r.setex(schema_deleted_key(tenant_id, org_id, name), ttl, json.dumps(data, default=str))


async def get_schema_cache(tenant_id: int, org_id: int, name: str) -> dict[str, Any] | None:
    """Read active schema from cache."""
    r = await get_redis()
    raw = await r.get(schema_key(tenant_id, org_id, name))
    if not raw:
        return None
    return json.loads(raw)


async def delete_schema_cache(tenant_id: int, org_id: int, name: str) -> None:
    """Remove schema keys."""
    r = await get_redis()
    await r.delete(schema_key(tenant_id, org_id, name), schema_deleted_key(tenant_id, org_id, name))


def capability_key(tenant_id: int, org_id: int, capability_name: str, rule_kind: str) -> str:
    """Capability registry cache key."""
    return get_settings().redis_key(
        "capability", str(tenant_id), str(org_id), capability_name, rule_kind
    )


def changelog_dedup_key(event_id: str) -> str:
    """Canal/API deduplication key."""
    return get_settings().redis_key("changelog", "dedup", event_id)


def changelog_pubsub_channel(tenant_id: int, org_id: int) -> str:
    """Pub/sub channel for SDK hot-reload."""
    return get_settings().redis_key("changelog", "pub", str(tenant_id), str(org_id))


async def set_capability_cache(
    tenant_id: int, org_id: int, capability_name: str, rule_kind: str, payload: dict[str, Any]
) -> None:
    """Cache active capability JSON."""
    r = await get_redis()
    await r.set(capability_key(tenant_id, org_id, capability_name, rule_kind), json.dumps(payload, default=str))


async def delete_capability_cache(
    tenant_id: int, org_id: int, capability_name: str, rule_kind: str
) -> None:
    """Remove capability cache."""
    r = await get_redis()
    await r.delete(capability_key(tenant_id, org_id, capability_name, rule_kind))


async def get_capability_cache(
    tenant_id: int, org_id: int, capability_name: str, rule_kind: str
) -> dict[str, Any] | None:
    """Read capability from cache."""
    r = await get_redis()
    raw = await r.get(capability_key(tenant_id, org_id, capability_name, rule_kind))
    if not raw:
        return None
    return json.loads(raw)


async def is_changelog_deduped(event_id: str) -> bool:
    """Return True if event_id was already processed."""
    r = await get_redis()
    return bool(await r.exists(changelog_dedup_key(event_id)))


async def mark_changelog_dedup(event_id: str, ttl_seconds: int) -> None:
    """Mark event_id as processed."""
    r = await get_redis()
    await r.setex(changelog_dedup_key(event_id), ttl_seconds, "1")


async def publish_sdk_changelog(tenant_id: int, org_id: int, event: dict[str, Any]) -> None:
    """Notify SDK subscribers via Redis pub/sub."""
    r = await get_redis()
    await r.publish(changelog_pubsub_channel(tenant_id, org_id), json.dumps(event, default=str))
