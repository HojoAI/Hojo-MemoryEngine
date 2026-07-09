"""Kafka consumer: schema-changelog → async Redis cache + SDK stream."""

from __future__ import annotations

import json
import logging
from typing import Any

from memory_engine.integrations import redis_cache
from memory_engine.services import schema_changelog as changelog_svc

logger = logging.getLogger(__name__)


async def handle_changelog_event(payload: dict[str, Any]) -> None:
    """Apply cache invalidation for unified changelog payload."""
    table = str(payload.get("table", "memory_field"))
    tenant_id = int(payload["tenant_id"])
    org_id = int(payload["org_id"])
    deleted = int(payload.get("deleted", 0))
    data = payload.get("payload") or {}

    if table == "memory_field":
        name = str(payload.get("memory_field_name") or data.get("name", ""))
        if not name:
            return
        if deleted == 1:
            await redis_cache.set_schema_deleted_cache(tenant_id, org_id, name, data, ttl=300)
            await redis_cache.delete_schema_cache(tenant_id, org_id, name)
            logger.info("schema deleted cache tenant=%s org=%s name=%s", tenant_id, org_id, name)
        elif data and data.get("id"):
            await redis_cache.set_schema_cache(tenant_id, org_id, name, data)
            logger.info("schema cache SET tenant=%s org=%s name=%s", tenant_id, org_id, name)
        else:
            await redis_cache.delete_schema_cache(tenant_id, org_id, name)
            logger.info("schema cache invalidate tenant=%s org=%s name=%s", tenant_id, org_id, name)

    elif table == "capability_registry":
        cap_name = str(data.get("capability_name") or payload.get("capability_name", ""))
        rule_kind = str(data.get("rule_kind") or payload.get("rule_kind", ""))
        if cap_name and rule_kind:
            if deleted == 1:
                await redis_cache.delete_capability_cache(tenant_id, org_id, cap_name, rule_kind)
            elif data:
                await redis_cache.set_capability_cache(tenant_id, org_id, cap_name, rule_kind, data)

    await changelog_svc.append_changelog_event(payload)


async def handle_schema_changelog_message(raw: bytes) -> None:
    """Process schema-changelog Kafka message (API or Canal-forwarded)."""
    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("invalid schema-changelog payload")
        return

    event_id = payload.get("event_id")
    if event_id and await redis_cache.is_changelog_deduped(str(event_id)):
        return
    if event_id:
        from memory_engine.config import get_settings

        await redis_cache.mark_changelog_dedup(
            str(event_id), get_settings().schema_changelog_dedup_ttl_seconds
        )

    await handle_changelog_event(payload)
