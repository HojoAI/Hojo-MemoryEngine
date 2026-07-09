"""Tests for memory retrieve and call services."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.schemas.memory_field import (
    DataCallRequest,
    DataRetrieveRequest,
    LLMConfig,
    RetrieveRuleBody,
)
from memory_engine.services import memory_retrieve as svc


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(tenant_id=1, org_id=1, user_id=1)


@pytest.fixture
def sample_doc() -> dict:
    return {
        "user_id": "u1",
        "memory_field_name": "用户年龄",
        "value": {"query": "22岁"},
        "deleted": 0,
    }


@pytest.mark.asyncio
async def test_explicit_exact_retrieve(ctx: RequestContext, sample_doc: dict) -> None:
    body = DataRetrieveRequest(
        user_id="u1",
        memory_field_name="用户年龄",
        rule=RetrieveRuleBody(method="EXACT"),
    )
    with (
        patch.object(svc.mf_service, "get_active_by_name", new_callable=AsyncMock) as mock_field,
        patch.object(svc.mongo_store, "get_memory_data", new_callable=AsyncMock) as mock_get,
    ):
        mock_field.return_value = object()
        mock_get.return_value = sample_doc
        out = await svc.retrieve(None, ctx, body)  # type: ignore[arg-type]
    assert out is not None
    assert out.value == {"query": "22岁"}
    assert out.retrieve_result is None


@pytest.mark.asyncio
async def test_explicit_llm_retrieve(ctx: RequestContext, sample_doc: dict) -> None:
    body = DataRetrieveRequest(
        user_id="u1",
        memory_field_name="用户年龄",
        rule=RetrieveRuleBody(
            method="LLM",
            prompt="是否可以考驾照",
            llm=LLMConfig(model_name="gpt-test"),
        ),
    )
    with (
        patch.object(svc.mf_service, "get_active_by_name", new_callable=AsyncMock) as mock_field,
        patch.object(svc.mongo_store, "get_memory_data", new_callable=AsyncMock) as mock_get,
        patch.object(svc, "_run_llm", new_callable=AsyncMock) as mock_llm,
    ):
        mock_field.return_value = object()
        mock_get.return_value = sample_doc
        mock_llm.return_value = "可以考取"
        out = await svc.retrieve(None, ctx, body)  # type: ignore[arg-type]
    assert out is not None
    assert out.retrieve_result == "可以考取"
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_implicit_llm_retrieve(ctx: RequestContext, sample_doc: dict) -> None:
    body = DataRetrieveRequest(
        user_id="u1",
        rule=RetrieveRuleBody(method="LLM", prompt="明天下午思考方案"),
    )
    llm_json = json.dumps(
        {"memory_field_name": "用户年龄", "answer": "已安排"},
        ensure_ascii=False,
    )
    with (
        patch.object(svc.mongo_store, "list_memory_data_for_user", new_callable=AsyncMock) as mock_list,
        patch.object(svc.mongo_store, "get_memory_data", new_callable=AsyncMock) as mock_get,
        patch.object(svc, "_run_llm", new_callable=AsyncMock) as mock_llm,
    ):
        mock_list.return_value = [sample_doc]
        mock_get.return_value = sample_doc
        mock_llm.return_value = llm_json
        out = await svc.retrieve(None, ctx, body)  # type: ignore[arg-type]
    assert out is not None
    assert out.memory_field_name == "用户年龄"
    assert out.retrieve_result == "已安排"


@pytest.mark.asyncio
async def test_call_with_llm(ctx: RequestContext) -> None:
    body = DataCallRequest(
        memory_field_name="用户年龄",
        prompt_template="年龄:{age} 问题:<是否可以考取驾照>",
        slot="{age}",
        mem_data="22",
        use_llm=True,
        llm=LLMConfig(model_name="gpt-test"),
    )
    with (
        patch.object(svc.mf_service, "get_active_by_name", new_callable=AsyncMock) as mock_field,
        patch.object(svc, "_run_llm", new_callable=AsyncMock) as mock_llm,
    ):
        mock_field.return_value = object()
        mock_llm.return_value = "可以"
        out = await svc.call_memory(None, ctx, body)  # type: ignore[arg-type]
    assert "22" in out.filled_prompt
    assert out.result == "可以"


@pytest.mark.asyncio
async def test_call_without_llm(ctx: RequestContext) -> None:
    body = DataCallRequest(
        memory_field_name="用户年龄",
        prompt_template="年龄:<slot>",
        slot="<slot>",
        mem_data="22",
        use_llm=False,
    )
    with patch.object(svc.mf_service, "get_active_by_name", new_callable=AsyncMock) as mock_field:
        mock_field.return_value = object()
        out = await svc.call_memory(None, ctx, body)  # type: ignore[arg-type]
    assert out.result == "年龄:22"
    assert out.filled_prompt == out.result


def test_parse_implicit_llm_response() -> None:
    name, answer = svc._parse_implicit_llm_response(
        '{"memory_field_name": "用户年龄", "answer": "ok"}'
    )
    assert name == "用户年龄"
    assert answer == "ok"

    name2, answer2 = svc._parse_implicit_llm_response('{"memory_field_name": null}')
    assert name2 is None
