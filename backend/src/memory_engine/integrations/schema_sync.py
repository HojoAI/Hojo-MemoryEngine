"""Publish schema change events (API fallback or Canal forward)."""

from __future__ import annotations

import uuid
from typing import Any

from memory_engine.config import get_settings
from memory_engine.integrations.kafka_producer import publish


def _api_publish_enabled() -> bool:
    """Whether API handlers publish changelog events to Kafka (set SCHEMA_SYNC_API_PUBLISH=false without Kafka)."""
    return get_settings().schema_sync_api_publish


async def publish_changelog_event(message: dict[str, Any]) -> None:
    """Emit unified changelog event to Kafka schema-changelog topic."""
    settings = get_settings()
    if "event_id" not in message:
        message = {**message, "event_id": f"api:{uuid.uuid4()}"}
    await publish(
        settings.kafka_schema_changelog_topic,
        message,
        key=_changelog_key(message),
    )


def _changelog_key(message: dict[str, Any]) -> str:
    table = message.get("table", "memory_field")
    tenant_id = message.get("tenant_id", 0)
    org_id = message.get("org_id", 0)
    if table == "memory_field":
        name = message.get("memory_field_name", "")
        return f"{tenant_id}:{org_id}:{name}"
    if table == "capability_registry":
        payload = message.get("payload") or {}
        return f"{tenant_id}:{org_id}:cap:{payload.get('capability_name')}:{payload.get('rule_kind')}"
    payload = message.get("payload") or {}
    return f"{tenant_id}:{org_id}:{table}:{payload.get('rule_name', '')}"


async def publish_memory_field_change(
    *,
    tenant_id: int,
    org_id: int,
    memory_field_name: str,
    event_type: str,
    deleted: int = 0,
    version: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit memory_field change (API path when Canal disabled or dual-write enabled)."""
    if not _api_publish_enabled():
        return

    message = {
        "source": "memory-engine-api",
        "event_id": f"api:memory_field:{tenant_id}:{org_id}:{memory_field_name}:{uuid.uuid4()}",
        "database": get_settings().canal_mysql_database,
        "table": "memory_field",
        "event_type": event_type,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "memory_field_name": memory_field_name,
        "deleted": deleted,
        "version": version,
        "payload": payload or {},
    }
    await publish_changelog_event(message)


async def publish_rule_change(
    *,
    table: str,
    tenant_id: int,
    org_id: int,
    memory_field_name: str,
    event_type: str,
    deleted: int = 0,
    version: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit parse/retrieve/call rule change."""
    if not _api_publish_enabled():
        return
    message = {
        "source": "memory-engine-api",
        "event_id": f"api:{table}:{tenant_id}:{org_id}:{memory_field_name}:{uuid.uuid4()}",
        "database": get_settings().canal_mysql_database,
        "table": table,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "memory_field_name": memory_field_name,
        "deleted": deleted,
        "version": version,
        "payload": payload or {},
    }
    await publish_changelog_event(message)
