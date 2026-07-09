"""Memory field list/create deduplication behavior."""

from __future__ import annotations

import re
from pathlib import Path


def test_list_active_dedupes_by_name_in_service() -> None:
    """``list_active`` must group by name and keep only the highest version."""
    path = Path(__file__).resolve().parents[1] / "src/memory_engine/services/memory_field.py"
    source = path.read_text(encoding="utf-8")
    assert "func.max(MemoryField.version)" in source
    assert ".group_by(MemoryField.name)" in source


def test_create_uses_mysql_advisory_lock() -> None:
    """Concurrent creates for the same name are serialized via GET_LOCK."""
    path = Path(__file__).resolve().parents[1] / "src/memory_engine/services/memory_field.py"
    source = path.read_text(encoding="utf-8")
    assert re.search(r"GET_LOCK\(:lock_key", source)
    assert "await _acquire_name_lock(session, ctx, body.name)" in source
