"""AML protocol and adapter behavior tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.api.deps import get_aml_request_context
from memory_engine.core.context import RequestContext
from memory_engine.main import app
from memory_engine.schemas.aml import (
    AMLAddRequest,
    AMLAddResponse,
    AMLSearchItem,
    AMLSearchRequest,
    AMLSearchResponse,
)
from memory_engine.services import aml_adapter


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=7, org_id=9, user_id=11)


def test_aml_tokens_normalize_english_and_chinese_phrases() -> None:
    assert "graduate" in aml_adapter._tokens("She graduated and likes hiking")
    assert "like" in aml_adapter._tokens("She graduated and likes hiking")
    assert "喜欢" in aml_adapter._tokens("我喜欢喝乌龙茶")
    assert "乌龙" in aml_adapter._tokens("我喜欢喝乌龙茶")


def test_explicit_match_rank_prioritizes_numbers_and_dates() -> None:
    ranked = aml_adapter._explicit_match_rank(
        "What happened on 2025-06-12 and cost $240?",
        [
            {"unit_id": "noise", "content": "A similar event cost $120 in 2024."},
            {"unit_id": "answer", "content": "On 2025-06-12 the repair cost $240."},
        ],
    )
    assert ranked[0][0] == "answer"


def test_temporal_rank_prefers_correction_for_current_state_only() -> None:
    units = [
        {
            "unit_id": "old",
            "content": "My shipping address is Hangzhou Wenyi Road 88.",
            "event_time_ms": 1_700_000_000_000,
        },
        {
            "unit_id": "new",
            "content": "I moved and updated my shipping address to Shanghai Yuyuan Road 120.",
            "event_time_ms": 1_800_000_000_000,
        },
    ]

    ranked = aml_adapter._temporal_rank("What is my current shipping address?", units)

    assert ranked[0][0] == "new"
    assert aml_adapter._temporal_rank("What was my address in 2025?", units) == []


def test_aggregation_rank_keeps_operands_and_role_bias_favors_user_evidence() -> None:
    units = [
        {"unit_id": "operand", "content": "I bought 4 plants.", "role": "user"},
        {"unit_id": "noise", "content": "We discussed the plants.", "role": "assistant"},
    ]

    assert aml_adapter._aggregation_rank("How many plants did I buy in total?", units) == [
        ("operand", 3.0)
    ]
    fused = {"operand": 1.0, "noise": 1.0}
    aml_adapter._apply_role_bias(
        fused,
        {unit["unit_id"]: unit for unit in units},
        user_boost=0.06,
        assistant_penalty=0.12,
    )
    assert fused["operand"] > fused["noise"]


def test_neighbor_evidence_and_session_diversity() -> None:
    by_id = {
        "a0": {"session_id": "a", "message_index": 0},
        "a1": {"session_id": "a", "message_index": 1},
        "a2": {"session_id": "a", "message_index": 2},
        "b0": {"session_id": "b", "message_index": 0},
    }
    fused = {"a1": 1.0, "a0": 0.9, "a2": 0.8, "b0": 0.7}
    aml_adapter._add_neighbor_evidence(
        fused,
        [("a1", 1.0)],
        by_id,
        seed_limit=1,
        window=1,
        weight=0.5,
        damping=0,
    )
    assert fused["a0"] > 0.9
    assert fused["a2"] > 0.8

    diversified = aml_adapter._diversify_by_session(
        [("a1", 1.0), ("a0", 0.9), ("a2", 0.8), ("b0", 0.7)],
        by_id,
        max_per_session=1,
    )
    assert [unit_id for unit_id, _score in diversified[:2]] == ["a1", "b0"]


@pytest.mark.asyncio
async def test_aml_routes_return_exact_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def override_context() -> RequestContext:
        return _ctx()

    async def fake_add(_ctx: RequestContext, body: AMLAddRequest) -> AMLAddResponse:
        return AMLAddResponse(
            request_id=body.request_id,
            user_id=body.user_id,
            session_id=body.session_id,
        )

    async def fake_search(_ctx: RequestContext, _body: AMLSearchRequest) -> AMLSearchResponse:
        return AMLSearchResponse(
            data=[
                AMLSearchItem(
                    id="aml_1",
                    content="[2026-01-01T00:00:00+00:00] user: remembered fact",
                    score=1.0,
                    created_at="2026-01-01T00:00:00+00:00",
                )
            ]
        )

    app.dependency_overrides[get_aml_request_context] = override_context
    monkeypatch.setattr(aml_adapter, "add", fake_add)
    monkeypatch.setattr(aml_adapter, "search", fake_search)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            add_response = await client.post(
                "/aml/add",
                json={
                    "request_id": "req-1",
                    "messages": [{"role": "user", "content": "remembered fact"}],
                    "user_id": "eval:user-1",
                    "session_id": "eval:session-1",
                },
            )
            search_response = await client.post(
                "/aml/search",
                json={"query": "what fact?", "user_id": "eval:user-1", "top_k": 100},
            )
    finally:
        app.dependency_overrides.clear()

    assert add_response.status_code == 200
    assert add_response.json() == {
        "success": True,
        "request_id": "req-1",
        "user_id": "eval:user-1",
        "session_id": "eval:session-1",
    }
    assert search_response.status_code == 200
    assert set(search_response.json()) == {"data"}
    assert search_response.json()["data"][0]["id"] == "aml_1"


@pytest.mark.asyncio
async def test_add_is_idempotent_after_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    body = AMLAddRequest.model_validate(
        {
            "request_id": "req-1",
            "messages": [{"role": "assistant", "content": "The launch is Friday."}],
            "user_id": "eval:user-1",
            "session_id": "eval:session-1",
        }
    )
    digest = aml_adapter._payload_hash(body)

    async def reserve(_record: dict) -> dict:
        return {"payload_hash": digest, "status": "complete"}

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("completed Add must not write again")

    monkeypatch.setattr(aml_adapter.aml_store, "reserve_add_request", reserve)
    monkeypatch.setattr(aml_adapter.aml_store, "upsert_units", should_not_run)
    monkeypatch.setattr(aml_adapter.qdrant_store, "upsert_aml_memory_units", should_not_run)

    result = await aml_adapter.add(_ctx(), body)
    assert result.success is True
    assert result.request_id == "req-1"


@pytest.mark.asyncio
async def test_add_requires_vector_index_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    body = AMLAddRequest.model_validate(
        {
            "request_id": "req-2",
            "messages": [{"role": "user", "content": "My dog is named Poppy."}],
            "user_id": "eval:user-2",
            "session_id": "eval:session-2",
        }
    )

    async def reserve(record: dict) -> dict:
        return record

    async def persist(_units: list[dict]) -> None:
        return None

    async def vector_failure(_units: list[dict]) -> None:
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(aml_adapter.aml_store, "reserve_add_request", reserve)
    monkeypatch.setattr(aml_adapter.aml_store, "upsert_units", persist)
    monkeypatch.setattr(aml_adapter.qdrant_store, "upsert_aml_memory_units", vector_failure)

    with pytest.raises(RuntimeError, match="qdrant unavailable"):
        await aml_adapter.add(_ctx(), body)


@pytest.mark.asyncio
async def test_search_fuses_channels_and_respects_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    units = [
        {
            "unit_id": "u1",
            "searchable_content": "[2026-01-01] user: My dog is named Poppy.",
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        {
            "unit_id": "u2",
            "searchable_content": "[2026-01-02] assistant: The cat is named Luna.",
            "occurred_at": "2026-01-02T00:00:00Z",
        },
    ]
    seen_user_ids: list[str] = []

    async def list_units(_tenant: int, _org: int, user_id: str, *, limit: int) -> list[dict]:
        seen_user_ids.append(user_id)
        assert limit >= 100
        return units

    async def vector_search(
        _tenant: int, _org: int, user_id: str, _query: str, *, limit: int
    ) -> list[dict]:
        seen_user_ids.append(user_id)
        assert limit >= 100
        return [{"unit_id": "u1", "score": 0.9}, {"unit_id": "u2", "score": 0.3}]

    monkeypatch.setattr(aml_adapter.aml_store, "list_units_for_user", list_units)
    monkeypatch.setattr(aml_adapter.qdrant_store, "search_aml_memory_units", vector_search)
    result = await aml_adapter.search(
        _ctx(),
        AMLSearchRequest(query="What is my dog's name?", user_id="eval:user-9", top_k=1),
    )

    assert seen_user_ids and set(seen_user_ids) == {"eval:user-9"}
    assert len(result.data) == 1
    assert result.data[0].id == "u1"
    assert "Poppy" in result.data[0].content


@pytest.mark.asyncio
async def test_add_llm_augmentation_keeps_raw_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    body = AMLAddRequest.model_validate(
        {
            "request_id": "req-llm-1",
            "messages": [{"role": "user", "content": "My dog is named Poppy."}],
            "user_id": "eval:user-llm",
            "session_id": "eval:session-llm",
        }
    )

    async def fake_completion(*_args, **_kwargs) -> tuple[str, int, int]:
        return '{"messages":[{"index":0,"terms":["Poppy", "dog name"]}]}', 1, 1

    monkeypatch.setattr(aml_adapter.llm_client, "chat_completion", fake_completion)
    settings = SimpleNamespace(
        aml_llm_add_augment_enabled=True,
        aml_llm_required=True,
        aml_llm_model="gpt-4o-mini",
    )
    terms = await aml_adapter._augment_message_terms(body, settings)
    units = aml_adapter._build_units(_ctx(), body, terms)

    assert "Poppy" in units[0]["content"]
    assert "[retrieval terms] Poppy dog name" in units[0]["searchable_content"]


@pytest.mark.asyncio
async def test_search_llm_rerank_only_returns_allowed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_completion(*_args, **_kwargs) -> tuple[str, int, int]:
        return '{"unit_ids":["u2", "unknown", "u1"]}', 1, 1

    monkeypatch.setattr(aml_adapter.llm_client, "chat_completion", fake_completion)
    settings = SimpleNamespace(
        aml_llm_rerank_enabled=True,
        aml_llm_required=True,
        aml_llm_model="gpt-4o-mini",
        aml_llm_rerank_candidates=50,
    )
    result = await aml_adapter._rerank_candidates(
        "What is remembered?",
        [
            {"unit_id": "u1", "content": "first"},
            {"unit_id": "u2", "content": "second"},
        ],
        settings,
    )

    assert result == ["u2", "u1"]


@pytest.mark.asyncio
async def test_aml_top_k_above_100_is_rejected() -> None:
    async def override_context() -> RequestContext:
        return _ctx()

    app.dependency_overrides[get_aml_request_context] = override_context
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/aml/search",
                json={"query": "q", "user_id": "eval:user-1", "top_k": 101},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
