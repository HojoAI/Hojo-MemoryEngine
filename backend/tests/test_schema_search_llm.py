"""Tests for schema LLM lookup (mode=LLM)."""

from unittest.mock import AsyncMock, patch

import pytest

from memory_engine.models.schema import MemoryField
from memory_engine.services.schema_search import _llm_pick, _parse_llm_pick_name


def _field(name: str) -> MemoryField:
    row = MemoryField()
    row.name = name
    row.deleted = 0
    return row


def test_parse_llm_pick_name_null() -> None:
    assert _parse_llm_pick_name('{"name": null}') is None
    assert _parse_llm_pick_name('{"name": ""}') is None


def test_parse_llm_pick_name_json_block() -> None:
    raw = '```json\n{"name": "用户性别"}\n```'
    assert _parse_llm_pick_name(raw) == "用户性别"


@pytest.mark.asyncio
async def test_llm_pick_returns_none_when_model_returns_null() -> None:
    rows = [_field("用户性别"), _field("用户年龄")]
    with patch(
        "memory_engine.services.schema_search.llm_client.chat_completion",
        new_callable=AsyncMock,
        return_value=('{"name": null}', None, None),
    ):
        assert await _llm_pick(rows, "天气") is None


@pytest.mark.asyncio
async def test_llm_pick_returns_matching_row() -> None:
    rows = [_field("用户性别"), _field("用户年龄")]
    with patch(
        "memory_engine.services.schema_search.llm_client.chat_completion",
        new_callable=AsyncMock,
        return_value=('{"name": "用户性别"}', None, None),
    ):
        picked = await _llm_pick(rows, "性别")
        assert picked is not None
        assert picked.name == "用户性别"


@pytest.mark.asyncio
async def test_llm_pick_returns_none_for_unknown_name() -> None:
    rows = [_field("用户性别")]
    with patch(
        "memory_engine.services.schema_search.llm_client.chat_completion",
        new_callable=AsyncMock,
        return_value=('{"name": "不存在的字段"}', None, None),
    ):
        assert await _llm_pick(rows, "性别") is None


@pytest.mark.asyncio
async def test_llm_pick_no_fallback_on_bad_json() -> None:
    rows = [_field("用户性别")]
    with patch(
        "memory_engine.services.schema_search.llm_client.chat_completion",
        new_callable=AsyncMock,
        return_value=("not json", None, None),
    ):
        assert await _llm_pick(rows, "性别") is None
