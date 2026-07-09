"""Kafka consumer: billing-events → mark events processed."""

from __future__ import annotations

import json
import logging
from typing import Any

from memory_engine.db.session import SessionLocal
from memory_engine.services import billing_service

logger = logging.getLogger(__name__)


async def handle_billing_event_message(raw: bytes) -> None:
    """Process billing event from Kafka."""
    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("invalid billing-events payload")
        return

    event_uuid = payload.get("event_uuid")
    if not event_uuid:
        return

    async with SessionLocal() as session:
        ok = await billing_service.process_billing_event(session, str(event_uuid))
    if ok:
        logger.info("billing event processed: %s", event_uuid)
