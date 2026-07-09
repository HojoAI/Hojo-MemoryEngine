"""Kafka event producer (billing, canal sync)."""

import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer

from memory_engine.config import get_settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None

_KAFKA_CONNECT_TIMEOUT_SECONDS = 3.0
_KAFKA_SEND_TIMEOUT_SECONDS = 5.0


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=get_settings().kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
        )
        await _producer.start()
    return _producer


async def publish(topic: str, payload: dict[str, Any], key: str | None = None) -> None:
    """Publish JSON message; never block the API request path for long."""
    if not get_settings().kafka_publish_enabled:
        return
    try:
        producer = await asyncio.wait_for(
            get_producer(), timeout=_KAFKA_CONNECT_TIMEOUT_SECONDS
        )
        await asyncio.wait_for(
            producer.send_and_wait(topic, payload, key=key.encode() if key else None),
            timeout=_KAFKA_SEND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.debug("kafka publish skipped: %s", exc)
