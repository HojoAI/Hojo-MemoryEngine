"""Consume Canal binlog topic, dedupe, forward to schema-changelog pipeline."""

from __future__ import annotations

import logging

from memory_engine.config import get_settings
from memory_engine.consumers.schema_changelog_consumer import handle_changelog_event
from memory_engine.integrations import canal_adapter, redis_cache, schema_sync

logger = logging.getLogger(__name__)


async def handle_canal_binlog_message(raw: bytes) -> None:
    """Parse Canal message and apply changelog side-effects."""
    events = canal_adapter.parse_canal_message(raw)
    if not events:
        return

    settings = get_settings()
    for event in events:
        event_id = str(event.get("event_id", ""))
        if event_id and await redis_cache.is_changelog_deduped(event_id):
            logger.debug("skip duplicate canal event %s", event_id)
            continue

        await handle_changelog_event(event)

        if event_id:
            await redis_cache.mark_changelog_dedup(
                event_id, settings.schema_changelog_dedup_ttl_seconds
            )

        if settings.canal_forward_to_schema_topic:
            await schema_sync.publish_changelog_event(event)
