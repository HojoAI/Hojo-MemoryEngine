"""Parse Alibaba Canal binlog messages into MemoryEngine changelog events."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CANAL_WATCHED_TABLES = frozenset(
    {
        "memory_field",
        "parse_rule",
        "retrieve_rule",
        "call_rule",
        "capability_registry",
    }
)

CANAL_TYPE_MAP = {
    "INSERT": "create",
    "UPDATE": "update",
    "DELETE": "delete",
}


def _row_value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    val = row.get(key, default)
    if val is None:
        return default
    if key == "deleted" and val not in (0, 1):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default
    return val


def _memory_field_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]) if row.get("id") is not None else None,
        "tenant_id": int(row["tenant_id"]),
        "org_id": int(row.get("org_id", 0)),
        "name": str(row["name"]),
        "description": row.get("description"),
        "value_type": row.get("value_type"),
        "match_method": row.get("match_method"),
        "storage_type": row.get("storage_type"),
        "version": int(row.get("version", 1)),
        "status": row.get("status"),
        "deleted": int(row.get("deleted", 0)),
    }


def _rule_payload(row: dict[str, Any], table: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": int(row["id"]) if row.get("id") is not None else None,
        "tenant_id": int(row["tenant_id"]),
        "org_id": int(row.get("org_id", 0)),
        "memory_field_name": row.get("memory_field_name"),
        "rule_name": row.get("rule_name"),
        "version": int(row.get("version", 1)),
        "deleted": int(row.get("deleted", 0)),
        "capability_id": int(row["capability_id"]) if row.get("capability_id") else None,
    }
    if table == "retrieve_rule":
        payload["retrieve_method"] = row.get("retrieve_method")
    if table == "call_rule":
        payload["slot_name"] = row.get("slot_name")
    return payload


def _capability_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]) if row.get("id") is not None else None,
        "tenant_id": int(row["tenant_id"]),
        "org_id": int(row.get("org_id", 0)),
        "capability_name": str(row["capability_name"]),
        "module_name": str(row["module_name"]),
        "service_name": str(row["service_name"]),
        "rule_kind": str(row["rule_kind"]),
        "slot_name": row.get("slot_name"),
        "enabled": int(row.get("enabled", 1)),
        "version": int(row.get("version", 1)),
        "deleted": int(row.get("deleted", 0)),
    }


def canal_row_to_changelog(
    *,
    database: str,
    table: str,
    canal_type: str,
    row: dict[str, Any],
    ts: int | None = None,
) -> dict[str, Any] | None:
    """Map one Canal row to unified schema-changelog payload."""
    if table not in CANAL_WATCHED_TABLES:
        return None

    event_type = CANAL_TYPE_MAP.get(canal_type.upper())
    if not event_type:
        return None

    deleted = _row_value(row, "deleted", 0)
    tenant_id = int(row["tenant_id"])
    org_id = int(row.get("org_id", 0))

    if table == "memory_field":
        payload = _memory_field_payload(row)
        memory_field_name = str(row["name"])
        if deleted == 1 or canal_type.upper() == "DELETE":
            deleted = 1
            payload = {"name": memory_field_name, "deleted": 1}
    elif table == "capability_registry":
        payload = _capability_payload(row)
        memory_field_name = ""
    else:
        payload = _rule_payload(row, table)
        memory_field_name = str(row.get("memory_field_name") or "")

    event_id = f"{database}:{table}:{row.get('id')}:{ts or 0}:{canal_type}"

    return {
        "source": "canal",
        "event_id": event_id,
        "database": database,
        "table": table,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "memory_field_name": memory_field_name,
        "deleted": deleted if table == "memory_field" else int(row.get("deleted", 0)),
        "version": int(row.get("version", 1)) if row.get("version") is not None else None,
        "payload": payload,
    }


def parse_canal_message(raw: bytes) -> list[dict[str, Any]]:
    """Parse Canal Kafka payload; returns zero or more changelog events."""
    try:
        doc: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("invalid canal message")
        return []

    if doc.get("isDdl"):
        return []

    database = str(doc.get("database", ""))
    table = str(doc.get("table", ""))
    canal_type = str(doc.get("type", "")).upper()
    ts = doc.get("ts")
    if isinstance(ts, str) and ts.isdigit():
        ts = int(ts)

    events: list[dict[str, Any]] = []
    data_rows: list[dict[str, Any]] = doc.get("data") or []
    if not data_rows and doc.get("table") in CANAL_WATCHED_TABLES:
        # flatMessage single row format
        if doc.get("tenant_id") is not None:
            data_rows = [doc]

    for row in data_rows:
        ev = canal_row_to_changelog(
            database=database,
            table=table,
            canal_type=canal_type,
            row=row,
            ts=ts if isinstance(ts, int) else None,
        )
        if ev:
            events.append(ev)
    return events
