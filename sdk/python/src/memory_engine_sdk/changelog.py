"""SDK schema hot-reload via Canal-backed changelog poll."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ChangelogCallback = Callable[[dict[str, Any]], None]


def _headers() -> dict[str, str]:
  h: dict[str, str] = {
    "X-Tenant-Id": os.environ.get("MEMORY_ENGINE_TENANT_ID", "1"),
    "X-Org-Id": os.environ.get("MEMORY_ENGINE_ORG_ID", "0"),
  }
  if uid := os.environ.get("MEMORY_ENGINE_USER_ID"):
    h["X-User-Id"] = uid
  if key := os.environ.get("MEMORY_ENGINE_API_KEY"):
    h["Authorization"] = f"Bearer {key}"
  return h


def _base_url() -> str:
  return os.environ.get("MEMORY_ENGINE_API_BASE", "http://127.0.0.1:6030/api/v1")


class SchemaChangelogWatcher:
  """Background poller: invalidate local schema cache on binlog changes."""

  def __init__(
    self,
    on_event: ChangelogCallback,
    *,
    poll_interval_ms: int | None = None,
    cursor: str = "0-0",
  ) -> None:
    self._on_event = on_event
    self._poll_interval_ms = poll_interval_ms or int(
      os.environ.get("MEMORY_ENGINE_CHANGELOG_POLL_MS", "2000")
    )
    self._cursor = cursor
    self._stop = threading.Event()
    self._thread: threading.Thread | None = None

  def start(self) -> None:
    if self._thread and self._thread.is_alive():
      return
    self._stop.clear()
    self._thread = threading.Thread(target=self._run, name="memory-engine-changelog", daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._stop.set()
    if self._thread:
      self._thread.join(timeout=5)

  def _run(self) -> None:
    url = f"{_base_url()}/schema/changelog/poll"
    while not self._stop.is_set():
      try:
        r = httpx.get(
          url,
          params={"cursor": self._cursor, "block_ms": min(self._poll_interval_ms, 30000)},
          headers=_headers(),
          timeout=35,
        )
        r.raise_for_status()
        body = r.json().get("data") or {}
        events = body.get("events") or []
        self._cursor = body.get("cursor") or self._cursor
        for ev in events:
          try:
            self._on_event(ev)
          except Exception:
            logger.exception("changelog callback error")
      except Exception:
        logger.debug("changelog poll failed", exc_info=True)
      if not self._stop.is_set():
        time.sleep(self._poll_interval_ms / 1000.0)


def watch_schema_changes(
  on_event: ChangelogCallback,
  *,
  auto_start: bool = True,
) -> SchemaChangelogWatcher:
  """Create and optionally start a changelog watcher (Canal → Redis Stream → poll)."""
  watcher = SchemaChangelogWatcher(on_event)
  if auto_start:
    watcher.start()
  return watcher
