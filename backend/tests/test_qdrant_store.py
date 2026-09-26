"""Regression tests for Qdrant vector lifecycle operations."""

import pytest

from memory_engine.integrations import qdrant_store


@pytest.mark.asyncio
async def test_mark_vectors_deleted_for_user_passes_filter_selector_as_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pinned Qdrant client requires ``points``, even for a filter."""

    class Client:
        def __init__(self) -> None:
            self.payload_call: dict | None = None

        async def scroll(self, **kwargs):
            return ([object()], None)

        async def set_payload(self, **kwargs) -> None:
            self.payload_call = kwargs

    client = Client()

    async def get_client():
        return client

    async def list_collections(_client):
        return {"memory_vectors_7"}

    monkeypatch.setattr(qdrant_store, "qdrant_is_available", lambda: True)
    monkeypatch.setattr(qdrant_store, "get_client", get_client)
    monkeypatch.setattr(qdrant_store, "_list_collection_names", list_collections)

    assert await qdrant_store.mark_vectors_deleted_for_user(7, 9, "user-1") == 1
    assert client.payload_call is not None
    assert "points" in client.payload_call
    assert "points_selector" not in client.payload_call


@pytest.mark.asyncio
async def test_ensure_payload_indexes_creates_all_claim_filter_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All fields used by semantic claim filtering are indexed idempotently."""

    class Client:
        def __init__(self) -> None:
            self.index_calls: list[dict] = []

        async def get_collection(self, collection: str):
            assert collection == "memory_vectors_7"
            return type("CollectionInfo", (), {"payload_schema": {}})()

        async def create_payload_index(self, **kwargs) -> None:
            self.index_calls.append(kwargs)

    client = Client()
    qdrant_store._payload_indexes_ready.clear()

    assert await qdrant_store.ensure_payload_indexes(client, "memory_vectors_7") is True
    assert [call["field_name"] for call in client.index_calls] == list(
        qdrant_store._CLAIM_PAYLOAD_INDEXES
    )
    assert all(call["wait"] is False for call in client.index_calls)
