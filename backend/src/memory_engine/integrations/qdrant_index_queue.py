"""Async Qdrant indexing queue (Mongo primary, vector index eventual consistency)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from memory_engine.integrations import qdrant_store

logger = logging.getLogger(__name__)

_queue: asyncio.Queue["IndexTask"] | None = None
_worker_task: asyncio.Task | None = None


@dataclass
class IndexTask:
    """Vector index task."""

    tenant_id: int
    org_id: int
    user_id: str
    memory_field_name: str
    doc_id: str
    text: str
    action: str = "upsert"


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        task = await _queue.get()
        try:
            if task.action == "delete":
                await qdrant_store.mark_deleted(
                    task.tenant_id, task.doc_id, task.memory_field_name
                )
            else:
                await qdrant_store.upsert_vector(
                    task.tenant_id,
                    task.org_id,
                    task.user_id,
                    task.memory_field_name,
                    task.doc_id,
                    task.text,
                )
        except Exception:
            logger.exception(
                "qdrant index failed tenant=%s field=%s",
                task.tenant_id,
                task.memory_field_name,
            )
        finally:
            _queue.task_done()


def start_qdrant_index_worker() -> None:
    """Start background worker (call from app lifespan)."""
    global _queue, _worker_task
    if _worker_task is not None:
        return
    _queue = asyncio.Queue(maxsize=10_000)
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("Qdrant async index worker started")


async def stop_qdrant_index_worker() -> None:
    """Cancel background worker."""
    global _worker_task, _queue
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None


def enqueue_vector_index(
    *,
    tenant_id: int,
    org_id: int,
    user_id: str,
    memory_field_name: str,
    doc_id: str,
    text: str,
    action: str = "upsert",
) -> None:
    """Enqueue vector indexing; no-op if worker not started."""
    if _queue is None:
        return
    try:
        _queue.put_nowait(
            IndexTask(
                tenant_id=tenant_id,
                org_id=org_id,
                user_id=user_id,
                memory_field_name=memory_field_name,
                doc_id=doc_id,
                text=text,
                action=action,
            )
        )
    except asyncio.QueueFull:
        logger.warning("qdrant index queue full, dropping task")


async def enqueue_vector_index_blocking(**kwargs: Any) -> None:
    """Fallback synchronous path when queue unavailable."""
    task = IndexTask(**kwargs)
    if task.action == "delete":
        await qdrant_store.mark_deleted(task.tenant_id, task.doc_id, task.memory_field_name)
    else:
        await qdrant_store.upsert_vector(
            task.tenant_id,
            task.org_id,
            task.user_id,
            task.memory_field_name,
            task.doc_id,
            task.text,
        )
