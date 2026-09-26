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
    # 六维会议/对话记忆。字段名以 pa-alg-agents 实际写入的为准
    # （meeting_memory_parse_service 的 schema_name，线上 schema/update?name= 可印证）。
    "偏好": "habit",
    "厌恶": "dislike",
    "习惯": "habit",
    "人脉知识": "social",
    "背景知识": "background",
    "短期目标": "goal",
    "程序性知识": "background",
    "背景知识-领域知识": "background",
    "背景知识-流程知识": "background",
    "偏好-关注领域": "habit",
    "日程-标题": "habit",
    "日程-时间": "habit",
    "日程-地点": "habit",
    "日程-习惯": "habit",
    "日程-描述": "habit",
    "日程-完成状态": "habit",
    "会议-主题": "background",
    "会议-决策": "goal",
    "会议-待办": "goal",
    "会议-纪要摘要": "background",
    "会议-用户承诺": "goal",
    "会议-纪要": "background",
    "会议-决策事项": "goal",
    "会议-待办任务": "goal",
    "投资人会议-压力点": "dislike",
    "投资人会议-投资人信号": "social",
    "投资人会议-投资人画像": "social",
    "投资人会议-经验教训": "background",
    "投资人会议-下一步": "goal",
    # Q1–Q4 对话引导已写入的 schema（列表维度映射）
    "首次引导用户画像": "background",
}

KB_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "背景知识-领域知识",
        "背景知识-流程知识",
        "偏好-关注领域",
    }
)

# Schedule-only schema names (legacy rows may lack ``source`` on the document).
SCHEDULE_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "日程-习惯",
        "日程-标题",
        "日程-时间",
        "日程-地点",
        "日程-描述",
        "日程-完成状态",
    }
)

# All memory_field_name values written by schedule memory parse (pa-alg-agents).
SCHEDULE_PARSE_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "日程-标题",
        "日程-时间",
        "日程-地点",
        "日程-习惯",
        "短期目标",
        "偏好",
        "人脉知识",
        "日程-描述",
        "日程-完成状态",
    }
)

# Investor-meeting schemas written by pa-alg-agents investor_memory.
INVESTOR_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "投资人会议-压力点",
        "投资人会议-投资人信号",
        "投资人会议-投资人画像",
        "投资人会议-经验教训",
        "投资人会议-下一步",
    }
)

# All memory_field_name values written by meeting memory parse (pa-alg-agents).
MEETING_PARSE_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "会议-主题",
        "会议-决策",
        "会议-待办",
        "人脉知识",
        "会议-纪要摘要",
        "短期目标",
        "会议-用户承诺",
        "会议-纪要",
        "会议-决策事项",
        "会议-待办任务",
        *INVESTOR_MEMORY_FIELDS,
    }
)

# Meeting-only schema names (legacy rows may lack ``source`` on the document).
MEETING_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "会议-主题",
        "会议-决策",
        "会议-待办",
        "会议-纪要摘要",
        "会议-用户承诺",
        "会议-纪要",
        "会议-决策事项",
        "会议-待办任务",
        *INVESTOR_MEMORY_FIELDS,
    }
)

MEMORY_SOURCE_LABELS: dict[str, str] = {
    "dialogue": "对话",
    "knowledge": "知识库",
    "meeting": "会议",
    "schedule": "日程",
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
    "meeting": "会议",
    "schedule": "日程",
}

# Detail page「生成方式」— mapped from module ``source``.
MEMORY_GENERATION_METHOD_LABELS: dict[str, str] = {
    "dialogue": "根据对话内容提取",
    "knowledge": "根据知识库文档内容提取",
    "schedule": "根据日程内容提取",
    "meeting": "根据会议内容提取",
}

# Detail page「最近使用」— written when algorithms retrieve/use memory.
MEMORY_RECENTLY_USED_LABELS: dict[str, str] = {
    "dialogue": "用于对话",
    "knowledge": "用于知识库",
    "schedule": "用于日程",
    "meeting": "用于会议",
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
    MEETING = "meeting"
    SCHEDULE = "schedule"


class MemoryItemStatus(StrEnum):
    """Memory item review status."""

    CONFIRMED = "confirmed"
    PENDING = "pending"


VALID_MEMORY_SOURCES: frozenset[str] = frozenset(
    {
        MemorySourceType.DIALOGUE.value,
        MemorySourceType.KNOWLEDGE.value,
        MemorySourceType.MEETING.value,
        MemorySourceType.SCHEDULE.value,
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


def infer_memory_source_from_parse_rule(parse_rule_name: str | None) -> str | None:
    """Infer UI source from parse rule name when ``source`` is omitted on write."""
    if not parse_rule_name or not parse_rule_name.strip():
        return None
    name = parse_rule_name.strip().lower()
    if name.startswith("schedule_"):
        return MemorySourceType.SCHEDULE.value
    if name.startswith("meeting_"):
        return MemorySourceType.MEETING.value
    return None


def resolve_write_memory_source(
    explicit_source: str | None,
    parse_rule_name: str | None = None,
) -> str | None:
    """Resolve memory write source: explicit ``source`` first, then parse rule prefix."""
    normalized = normalize_memory_source(explicit_source)
    if normalized is not None:
        return normalized
    return infer_memory_source_from_parse_rule(parse_rule_name)


def resolve_dimension(memory_field_name: str) -> str:
    """Map schema field name to UI dimension type.

    兜底必须是 ``MEMORY_DIMENSION_LABELS`` 里的合法维度，否则 UI 拿到的 dimension
    查不到对应标签；``_dimension_filter_clause`` 也已把未登记字段归到 background。
    """
    return MEMORY_FIELD_TO_DIMENSION.get(memory_field_name, "background")


def resolve_dimension_label(memory_field_name: str) -> str:
    """Display label aligned with dashboard ``memory_field_name`` column."""
    return memory_field_name


def resolve_default_source(memory_field_name: str) -> str:
    """Infer default source from memory field name when document has no ``source``."""
    if memory_field_name in KB_MEMORY_FIELDS:
        return MemorySourceType.KNOWLEDGE.value
    if memory_field_name in SCHEDULE_MEMORY_FIELDS:
        return MemorySourceType.SCHEDULE.value
    if memory_field_name in MEETING_MEMORY_FIELDS:
        return MemorySourceType.MEETING.value
    return MemorySourceType.DIALOGUE.value


def resolve_memory_source(doc: dict[str, Any]) -> str:
    """Resolve UI/API source from memory_data document."""
    stored = doc.get("source")
    if isinstance(stored, str) and stored.strip():
        return stored.strip().lower()
    memory_field_name = doc.get("memory_field_name") or ""
    return resolve_default_source(memory_field_name)
