"""Schemas for user memory list API (same granularity as memory_data / list-all)."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from memory_engine.constants.user_memory_item import (
    MEMORY_SOURCE_DETAIL_LABELS,
    MEMORY_SOURCE_LABELS,
    MEMORY_STATUS_DETAIL_LABELS,
    MEMORY_STATUS_LABELS,
    MemoryItemStatus,
    resolve_dimension,
    resolve_dimension_label,
    resolve_memory_source,
)


class UserMemoryItemOut(BaseModel):
    """One personal memory row for end-user list (one memory_data document)."""

    item_id: str
    user_id: str
    dimension: str = Field(..., description="background | social | goal | habit | dislike")
    dimension_label: str = Field(..., description="UI label, e.g. 背景知识")
    source: str = Field(..., description="dialogue | knowledge")
    source_label: str = Field(..., description="UI label, e.g. 对话")
    status: str = Field(..., description="confirmed | pending")
    status_label: str = Field(..., description="UI label, e.g. 已确认")
    content: str
    memory_field_name: str
    source_detail: str | None = None
    sensitive: bool = False
    created_at: str
    updated_at: str


class UserMemoryItemListPage(BaseModel):
    """Paginated list with offset/limit metadata."""

    page_id: int = Field(..., serialization_alias="pageId")
    page_size: int = Field(..., serialization_alias="pageSize")
    total_count: int = Field(..., serialization_alias="totalCount")
    page_content: list[UserMemoryItemOut] = Field(
        default_factory=list, serialization_alias="pageContent"
    )

    model_config = {"populate_by_name": True}


class UserMemoryGenerationBasisOut(BaseModel):
    """Generation basis section on memory detail page."""

    source: str
    source_label: str = Field(..., serialization_alias="sourceLabel")
    record_time: str = Field(..., serialization_alias="recordTime")

    model_config = {"populate_by_name": True}


class UserMemoryItemDetailOut(BaseModel):
    """Memory detail for end-user detail page."""

    item_id: str = Field(..., serialization_alias="itemId")
    user_id: str = Field(..., serialization_alias="userId")
    dimension: str
    dimension_label: str = Field(..., serialization_alias="dimensionLabel")
    status: str
    status_label: str = Field(..., serialization_alias="statusLabel")
    content: str
    time: str = Field(..., description="Display time from updated_at, YYYY-MM-DD HH:mm")
    memory_field_name: str = Field(..., serialization_alias="memoryFieldName")
    sensitive: bool | None = None
    generation_basis: UserMemoryGenerationBasisOut = Field(
        ..., serialization_alias="generationBasis"
    )

    model_config = {"populate_by_name": True}


def format_memory_value(value: Any) -> str:
    """Render memory_data.value as display text (aligned with dashboard JSON.stringify)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_display_time(iso_str: str) -> str:
    """Format ISO timestamp for detail page ``时间`` field."""
    return _parse_iso_datetime(iso_str).strftime("%Y-%m-%d %H:%M")


def format_record_date(iso_str: str) -> str:
    """Format ISO timestamp as record date ``YYYY-MM-DD``."""
    return _parse_iso_datetime(iso_str).strftime("%Y-%m-%d")


def build_item_out(doc: dict[str, Any]) -> UserMemoryItemOut:
    """Build list row from one memory_data document (no value splitting)."""
    memory_field_name = doc["memory_field_name"]
    dimension = resolve_dimension(memory_field_name)
    source = resolve_memory_source(doc)
    status = MemoryItemStatus.CONFIRMED.value
    updated_at = doc.get("updated_at") or ""
    created_at = doc.get("create_time") or updated_at
    return UserMemoryItemOut(
        item_id=doc["_id"],
        user_id=doc["user_id"],
        dimension=dimension,
        dimension_label=resolve_dimension_label(memory_field_name),
        source=source,
        source_label=MEMORY_SOURCE_LABELS.get(source, source),
        status=status,
        status_label=MEMORY_STATUS_LABELS.get(status, status),
        content=format_memory_value(doc.get("value")),
        memory_field_name=memory_field_name,
        source_detail=None,
        sensitive=False,
        created_at=created_at,
        updated_at=updated_at,
    )


def build_item_detail_out(doc: dict[str, Any]) -> UserMemoryItemDetailOut:
    """Build detail response from one memory_data document."""
    memory_field_name = doc["memory_field_name"]
    dimension = resolve_dimension(memory_field_name)
    source = resolve_memory_source(doc)
    status = MemoryItemStatus.CONFIRMED.value
    create_time = doc.get("create_time") or doc.get("updated_at") or ""
    updated_at = doc.get("updated_at") or create_time
    return UserMemoryItemDetailOut(
        item_id=doc["_id"],
        user_id=doc["user_id"],
        dimension=dimension,
        dimension_label=resolve_dimension_label(memory_field_name),
        status=status,
        status_label=MEMORY_STATUS_DETAIL_LABELS.get(status, status),
        content=format_memory_value(doc.get("value")),
        time=format_display_time(updated_at),
        memory_field_name=memory_field_name,
        sensitive=None,
        generation_basis=UserMemoryGenerationBasisOut(
            source=source,
            source_label=MEMORY_SOURCE_DETAIL_LABELS.get(
                source, MEMORY_SOURCE_LABELS.get(source, source)
            ),
            record_time=format_record_date(create_time),
        ),
    )
