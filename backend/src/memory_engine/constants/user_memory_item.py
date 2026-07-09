"""User memory item dimension / source / status constants."""

from enum import StrEnum
from typing import Any

# Memory dimension types (UI: 类型)
MEMORY_DIMENSION_LABELS: dict[str, str] = {
    "background": "背景知识",
    "social": "人脉知识",
    "goal": "目标",
    "habit": "习惯",
    "dislike": "厌恶",
}

MEMORY_FIELD_TO_DIMENSION: dict[str, str] = {
    "偏好": "habit",
    "偏好厌恶": "dislike",
    "人脉知识": "social",
    "背景知识习惯": "background",
    "短期目标": "goal",
    "程序性知识": "background",
    "背景知识-领域知识": "background",
    "背景知识-流程知识": "background",
    "偏好-关注领域": "habit",
}

KB_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "背景知识-领域知识",
        "背景知识-流程知识",
        "偏好-关注领域",
    }
)

MEMORY_SOURCE_LABELS: dict[str, str] = {
    "dialogue": "对话",
    "knowledge": "知识库",
}

MEMORY_STATUS_LABELS: dict[str, str] = {
    "confirmed": "已确认",
    "pending": "待确认",
}

MEMORY_STATUS_DETAIL_LABELS: dict[str, str] = {
    "confirmed": "启用中",
    "pending": "待确认",
}

MEMORY_SOURCE_DETAIL_LABELS: dict[str, str] = {
    "dialogue": "主对话",
    "knowledge": "知识库",
}


class MemoryDimensionType(StrEnum):
    """Memory dimension filter values."""

    BACKGROUND = "background"
    SOCIAL = "social"
    GOAL = "goal"
    HABIT = "habit"
    DISLIKE = "dislike"


class MemorySourceType(StrEnum):
    """Memory source filter values."""

    DIALOGUE = "dialogue"
    KNOWLEDGE = "knowledge"


class MemoryItemStatus(StrEnum):
    """Memory item review status."""

    CONFIRMED = "confirmed"
    PENDING = "pending"


VALID_MEMORY_SOURCES: frozenset[str] = frozenset(
    {
        MemorySourceType.DIALOGUE.value,
        MemorySourceType.KNOWLEDGE.value,
    }
)


def normalize_memory_source(source: str | None) -> str | None:
    """Normalize API/source payload; return None when omitted."""
    if source is None:
        return None
    normalized = source.strip().lower()
    if not normalized:
        return None
    if normalized not in VALID_MEMORY_SOURCES:
        raise ValueError(
            f"invalid memory source '{source}'; expected one of {sorted(VALID_MEMORY_SOURCES)}"
        )
    return normalized


def resolve_write_memory_source(
    explicit_source: str | None,
    parse_rule_name: str | None = None,
) -> str | None:
    """Resolve memory write source from explicit ``source`` only."""
    _ = parse_rule_name
    return normalize_memory_source(explicit_source)


def resolve_dimension(memory_field_name: str) -> str:
    """Map schema field name to UI dimension type."""
    return MEMORY_FIELD_TO_DIMENSION.get(memory_field_name, "background")


def resolve_dimension_label(memory_field_name: str) -> str:
    """Display label aligned with dashboard ``memory_field_name`` column."""
    return memory_field_name


def resolve_default_source(memory_field_name: str) -> str:
    """Infer default source from memory field name when document has no ``source``."""
    if memory_field_name in KB_MEMORY_FIELDS:
        return MemorySourceType.KNOWLEDGE.value
    return MemorySourceType.DIALOGUE.value


def resolve_memory_source(doc: dict[str, Any]) -> str:
    """Resolve UI/API source from memory_data document."""
    stored = doc.get("source")
    if isinstance(stored, str) and stored.strip():
        return stored.strip().lower()
    memory_field_name = doc.get("memory_field_name") or ""
    return resolve_default_source(memory_field_name)
