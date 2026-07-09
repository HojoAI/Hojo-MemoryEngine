"""Tests for memory source persistence and UI resolution."""

import pytest

from memory_engine.constants.user_memory_item import (
    MemorySourceType,
    normalize_memory_source,
    resolve_default_source,
    resolve_dimension_label,
    resolve_memory_source,
    resolve_write_memory_source,
)
from memory_engine.schemas.user_memory_item import (
    build_item_detail_out,
    build_item_out,
)


def test_resolve_memory_source_prefers_document_field() -> None:
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": "偏好",
        "source": "knowledge",
        "value": "下午跑步",
        "updated_at": "2026-06-26T00:00:00+00:00",
        "create_time": "2026-06-26T00:00:00+00:00",
    }
    assert resolve_memory_source(doc) == MemorySourceType.KNOWLEDGE.value


def test_resolve_memory_source_falls_back_to_field_default() -> None:
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": "偏好",
        "value": "每周一通勤",
        "updated_at": "2026-06-26T00:00:00+00:00",
    }
    assert resolve_memory_source(doc) == MemorySourceType.DIALOGUE.value


def test_build_item_detail_out_knowledge_source_label() -> None:
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": "背景知识-领域知识",
        "source": "knowledge",
        "value": "机器学习",
        "updated_at": "2026-06-26T09:15:00+00:00",
        "create_time": "2026-06-26T09:15:00+00:00",
    }
    detail = build_item_detail_out(doc)
    assert detail.generation_basis.source == MemorySourceType.KNOWLEDGE.value
    assert detail.generation_basis.source_label == "知识库"


def test_build_item_out_dialogue_fallback_without_source() -> None:
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": "偏好",
        "value": "喜欢手冲咖啡",
        "updated_at": "2026-06-26T00:00:00+00:00",
    }
    item = build_item_out(doc)
    assert item.source == MemorySourceType.DIALOGUE.value
    assert item.source_label == "对话"
    assert item.dimension_label == "偏好"


def test_build_item_out_field_label_matches_dashboard() -> None:
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": "短期目标",
        "source": "dialogue",
        "value": "完成季度 OKR",
        "updated_at": "2026-07-04T00:00:00+00:00",
        "create_time": "2026-07-04T00:00:00+00:00",
    }
    item = build_item_out(doc)
    assert item.dimension == "goal"
    assert item.dimension_label == "短期目标"
    assert item.content == "完成季度 OKR"
    assert item.source == MemorySourceType.DIALOGUE.value
    assert item.memory_field_name == "短期目标"


def test_normalize_memory_source_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_memory_source("invalid")


def test_normalize_memory_source_rejects_legacy_pa_sources() -> None:
    with pytest.raises(ValueError):
        normalize_memory_source("schedule")
    with pytest.raises(ValueError):
        normalize_memory_source("meeting")


def test_resolve_default_source_knowledge_field() -> None:
    assert resolve_default_source("背景知识-领域知识") == MemorySourceType.KNOWLEDGE.value


def test_resolve_default_source_dialogue_field() -> None:
    assert resolve_default_source("偏好") == MemorySourceType.DIALOGUE.value


def test_resolve_write_memory_source_uses_explicit_only() -> None:
    assert resolve_write_memory_source(
        "dialogue",
        "some_parse_rule_v1",
    ) == MemorySourceType.DIALOGUE.value


def test_resolve_write_memory_source_ignores_parse_rule_when_source_omitted() -> None:
    assert resolve_write_memory_source(None, "some_parse_rule_v1") is None


@pytest.mark.parametrize(
    "memory_field_name",
    [
        "偏好",
        "偏好厌恶",
        "人脉知识",
        "短期目标",
        "背景知识-领域知识",
        "背景知识-流程知识",
        "偏好-关注领域",
    ],
)
def test_core_memory_fields_label_matches_dashboard(memory_field_name: str) -> None:
    assert resolve_dimension_label(memory_field_name) == memory_field_name
    doc = {
        "_id": "abc",
        "user_id": "u1",
        "memory_field_name": memory_field_name,
        "source": MemorySourceType.DIALOGUE.value,
        "value": "样例内容",
        "updated_at": "2026-07-04T00:00:00+00:00",
        "create_time": "2026-07-04T00:00:00+00:00",
    }
    item = build_item_out(doc)
    assert item.dimension_label == memory_field_name
    assert item.memory_field_name == memory_field_name
