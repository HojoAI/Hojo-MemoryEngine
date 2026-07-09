"""Schema changelog stream for SDK hot-reload (Redis Stream)."""

from __future__ import annotations

import json
import time
from typing import Any

from memory_engine.config import get_settings
from memory_engine.integrations import redis_cache


def _stream_key(tenant_id: int, org_id: int) -> str:
    return get_settings().redis_key("changelog", "stream", str(tenant_id), str(org_id))


async def append_changelog_event(event: dict[str, Any]) -> str:
    """Append event to tenant/org Redis stream; return entry id."""
    tenant_id = int(event["tenant_id"])
    org_id = int(event["org_id"])
    r = await redis_cache.get_redis()
    entry_id: str = await r.xadd(
        _stream_key(tenant_id, org_id),
        {"json": json.dumps(event, default=str)},
        maxlen=10_000,
        approximate=True,
    )
    await redis_cache.publish_sdk_changelog(tenant_id, org_id, event)
    return entry_id


async def poll_changelog(
    tenant_id: int,
    org_id: int,
    *,
    cursor: str = "0-0",
    block_ms: int = 0,
    count: int = 50,
) -> tuple[list[dict[str, Any]], str]:
    """Read changelog entries after cursor; returns (events, next_cursor)."""
    r = await redis_cache.get_redis()
    key = _stream_key(tenant_id, org_id)
    start = cursor if cursor and cursor != "0-0" else "0-0"
    if block_ms > 0:
        rows = await r.xread({key: start}, count=count, block=block_ms)
    else:
        rows = await r.xread({key: start}, count=count)

    events: list[dict[str, Any]] = []
    next_cursor = cursor
    for _stream, entries in rows or []:
        for entry_id, fields in entries:
            next_cursor = entry_id
            raw = fields.get("json") if isinstance(fields, dict) else None
            if raw:
                events.append(json.loads(raw))
    if not events:
        next_cursor = cursor
    return events, next_cursor


async def stream_changelog(
    tenant_id: int,
    org_id: int,
    *,
    cursor: str = "0-0",
    timeout_seconds: int = 60,
):
    """Async generator for SSE: yield changelog dicts until timeout."""
    current = cursor
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        events, current = await poll_changelog(
            tenant_id, org_id, cursor=current, block_ms=5000, count=20
        )
        for ev in events:
            yield {**ev, "_cursor": current}
