"""P1 deterministic Memory Claim update behavior."""

from types import SimpleNamespace

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.schemas.memory_claim import MemoryClaimInput, MemoryIngestRequest, MemoryNamespace
from memory_engine.schemas.memory_claim import MemorySourceEventInput
from memory_engine.services import memory_claim


def _request(value: object, *, fact_status: str = "stated") -> MemoryIngestRequest:
    return MemoryIngestRequest(
        user_id="user-1",
        namespace=MemoryNamespace(type="financing_project", id="deal-1"),
        source_event=MemorySourceEventInput(
            source_type="meeting", meeting_id="meeting-1", raw_text="evidence"
        ),
        claims=[
            MemoryClaimInput(
                dimension="financing_terms",
                claim_type="valuation",
                claim_key="pre_money_valuation",
                value=value,
                text=str(value),
                fact_status=fact_status,
            )
        ],
    )


def _timed_request(value: object, occurred_at: str) -> MemoryIngestRequest:
    body = _request(value)
    return body.model_copy(
        update={"source_event": body.source_event.model_copy(update={"occurred_at": occurred_at})}
    )


@pytest.mark.asyncio
async def test_newer_stated_fact_supersedes_but_older_replay_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: list[dict] = []
    current: dict | None = None
    status_changes: list[tuple[str, dict]] = []

    async def get_latest(identity_id: str):
        return current

    async def insert(doc: dict, *, make_current: bool):
        nonlocal current
        stored = {**doc, "claim_id": f"claim-{len(claims) + 1}"}
        claims.append(stored)
        if make_current:
            current = stored
        return stored

    async def mark(claim_id: str, status: str, **extra):
        status_changes.append((status, extra))

    async def no_field(*args, **kwargs):
        return None

    async def no_index(*args, **kwargs):
        return None

    monkeypatch.setattr(memory_claim.memory_claim_store, "get_latest_claim", get_latest)
    monkeypatch.setattr(memory_claim.memory_claim_store, "insert_claim", insert)
    monkeypatch.setattr(memory_claim.memory_claim_store, "mark_claim_status", mark)
    monkeypatch.setattr(memory_claim.memory_field_service, "get_active_by_name", no_field)
    monkeypatch.setattr(memory_claim, "_index_claim_best_effort", no_index)
    monkeypatch.setattr(memory_claim, "_delete_claim_index_best_effort", no_index)
    monkeypatch.setattr(
        memory_claim, "get_settings", lambda: SimpleNamespace(
            memory_claim_min_confidence=0.8, memory_claim_vector_enabled=False
        )
    )
    ctx = RequestContext(tenant_id=1, org_id=2, user_id=3)

    first = await memory_claim._ingest_one(
        SimpleNamespace(), ctx, _timed_request("old", "2024-01-01T00:00:00Z"),
        _timed_request("old", "2024-01-01T00:00:00Z").claims[0], "event-1",
    )
    newer_body = _timed_request("new", "2024-02-01T00:00:00Z")
    newer = await memory_claim._ingest_one(
        SimpleNamespace(), ctx, newer_body, newer_body.claims[0], "event-2"
    )
    older_body = _timed_request("stale", "2024-01-15T00:00:00Z")
    older = await memory_claim._ingest_one(
        SimpleNamespace(), ctx, older_body, older_body.claims[0], "event-3"
    )

    assert [first.action, newer.action, older.action] == ["ADD", "SUPERSEDE", "CONFLICT"]
    assert status_changes == [
        ("superseded", {"superseded_by": "claim-2", "superseded_at": "2024-02-01T00:00:00+00:00"})
    ]
    assert current is not None and current["value"] == "new"


@pytest.mark.asyncio
async def test_claim_add_confirm_conflict_and_correction(monkeypatch: pytest.MonkeyPatch) -> None:
    claims: list[dict] = []
    current: dict | None = None

    async def save_event(*args, **kwargs):
        return "event-1"

    async def get_latest(identity_id: str):
        return current

    async def insert(doc: dict, *, make_current: bool):
        nonlocal current
        stored = {**doc, "claim_id": f"claim-{len(claims) + 1}", "revision": len(claims) + 1}
        claims.append(stored)
        if make_current:
            current = stored
        return stored

    async def confirm(*args, **kwargs):
        return current

    async def mark(claim_id: str, status: str, **extra):
        return None

    async def no_field(*args, **kwargs):
        return None

    async def no_index(*args, **kwargs):
        return None

    monkeypatch.setattr(memory_claim.memory_claim_store, "save_source_event", save_event)
    monkeypatch.setattr(memory_claim.memory_claim_store, "get_latest_claim", get_latest)
    monkeypatch.setattr(memory_claim.memory_claim_store, "insert_claim", insert)
    monkeypatch.setattr(memory_claim.memory_claim_store, "confirm_claim", confirm)
    monkeypatch.setattr(memory_claim.memory_claim_store, "mark_claim_status", mark)
    monkeypatch.setattr(memory_claim.memory_field_service, "get_active_by_name", no_field)
    monkeypatch.setattr(memory_claim.qdrant_store, "upsert_claim_vector", no_index)
    monkeypatch.setattr(
        memory_claim, "get_settings", lambda: SimpleNamespace(
            memory_claim_min_confidence=0.8, memory_claim_vector_enabled=False
        )
    )
    ctx = RequestContext(tenant_id=1, org_id=2, user_id=3)
    session = SimpleNamespace()

    added = await memory_claim.ingest(session, ctx, _request(100))
    confirmed = await memory_claim.ingest(session, ctx, _request(100))
    conflicted = await memory_claim.ingest(session, ctx, _request(120))
    corrected = await memory_claim.ingest(
        session, ctx, _request(130, fact_status="correction")
    )

    assert [
        added.decisions[0].action,
        confirmed.decisions[0].action,
        conflicted.decisions[0].action,
        corrected.decisions[0].action,
    ] == ["ADD", "CONFIRM", "CONFLICT", "SUPERSEDE"]


@pytest.mark.asyncio
async def test_json_schema_rejects_invalid_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    async def save_event(*args, **kwargs):
        return "event-1"

    async def field(*args, **kwargs):
        return SimpleNamespace(
            json_schema={
                "type": "object",
                "required": ["amount"],
                "properties": {"amount": {"type": "number"}},
            }
        )

    monkeypatch.setattr(memory_claim.memory_claim_store, "save_source_event", save_event)
    monkeypatch.setattr(memory_claim.memory_field_service, "get_active_by_name", field)
    result = await memory_claim.ingest(
        SimpleNamespace(),
        RequestContext(tenant_id=1),
        _request({"amount": "not-a-number"}),
    )
    assert result.decisions[0].action == "REJECT"
    assert "JSON Schema" in result.decisions[0].reason
