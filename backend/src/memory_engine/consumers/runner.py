"""Background Kafka consumer runner."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from aiokafka import AIOKafkaConsumer

from memory_engine.config import get_settings
from memory_engine.consumers.billing_events_consumer import handle_billing_event_message
from memory_engine.consumers.canal_binlog_consumer import handle_canal_binlog_message
from memory_engine.consumers.schema_changelog_consumer import handle_schema_changelog_message

logger = logging.getLogger(__name__)

Handler = Callable[[bytes], Awaitable[None]]

_consumers: list[AIOKafkaConsumer] = []
_tasks: list[asyncio.Task] = []


async def _consume_loop(consumer: AIOKafkaConsumer, handler: Handler, name: str) -> None:
    try:
        await consumer.start()
        logger.info("Kafka consumer started: %s", name)
        async for msg in consumer:
            try:
                await handler(msg.value)
            except Exception:
                logger.exception("handler error topic=%s", name)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("consumer loop failed: %s", name)
    finally:
        await consumer.stop()


async def start_kafka_consumers() -> None:
    """Start schema-changelog and billing-events consumers."""
    settings = get_settings()
    if not settings.kafka_consumers_enabled:
        return

    groups: list[tuple[str, str, Handler]] = [
        (settings.kafka_schema_changelog_topic, "memory-engine-schema-cache", handle_schema_changelog_message),
        (settings.kafka_billing_events_topic, "memory-engine-billing", handle_billing_event_message),
    ]
    if settings.canal_enabled:
        groups.insert(
            0,
            (settings.kafka_canal_topic, "memory-engine-canal-binlog", handle_canal_binlog_message),
        )
    for topic, group_id, handler in groups:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
        )
        _consumers.append(consumer)
        _tasks.append(asyncio.create_task(_consume_loop(consumer, handler, topic)))


async def stop_kafka_consumers() -> None:
    """Cancel consumer tasks and stop clients."""
    for task in _tasks:
        task.cancel()
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()
    _consumers.clear()
