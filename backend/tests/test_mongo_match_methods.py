"""Unit tests for OVERWRITE / APPEND / MERGE logic (mocked Mongo)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory_engine.integrations import mongo_store


def _mock_db(existing: dict | None) -> MagicMock:
    db = MagicMock()
    db.memory_data.find_one = AsyncMock(return_value=existing)
    db.memory_data.replace_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_overwrite_replaces_value() -> None:
    stored: dict = {}

    async def replace_one(filter_doc: dict, doc: dict, upsert: bool = False) -> None:
        stored["doc"] = doc

    db = _mock_db(None)
    db.memory_data.replace_one = replace_one

    with patch.object(mongo_store, "get_db", AsyncMock(return_value=db)):
        await mongo_store.upsert_memory_data(1, 1, "u1", "f", {"a": 1}, match_method="OVERWRITE")
        await mongo_store.upsert_memory_data(1, 1, "u1", "f", {"b": 2}, match_method="OVERWRITE")

    assert stored["doc"]["value"] == {"b": 2}


@pytest.mark.asyncio
async def test_append_extends_list() -> None:
    existing = {
        "_id": "x",
        "value": [1],
        "deleted": 0,
    }
    captured: dict = {}

    async def replace_one(filter_doc: dict, doc: dict, upsert: bool = False) -> None:
        captured["value"] = doc["value"]

    db = _mock_db(existing)
    db.memory_data.replace_one = replace_one

    with patch.object(mongo_store, "get_db", AsyncMock(return_value=db)):
        await mongo_store.upsert_memory_data(1, 1, "u2", "f", [2], match_method="APPEND")

    assert captured["value"] == [1, 2]


@pytest.mark.asyncio
async def test_merge_at_store_layer_overwrites_value() -> None:
    """MERGE LLM fusion runs in memory_data service; mongo_store receives merged value."""
    existing = {
        "_id": "x",
        "value": {"x": 1, "y": 1},
        "deleted": 0,
    }
    captured: dict = {}

    async def replace_one(filter_doc: dict, doc: dict, upsert: bool = False) -> None:
        captured["value"] = doc["value"]

    db = _mock_db(existing)
    db.memory_data.replace_one = replace_one

    with patch.object(mongo_store, "get_db", AsyncMock(return_value=db)):
        await mongo_store.upsert_memory_data(
            1, 1, "u3", "f", {"y": 2, "z": 3}, match_method="MERGE"
        )

    assert captured["value"] == {"y": 2, "z": 3}
