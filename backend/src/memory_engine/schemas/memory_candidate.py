"""Schemas for M13 memory candidate extraction and comparison."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryCategory = Literal["identity", "projects", "preferences", "terms"]
Sensitivity = Literal["normal", "sensitive", "prohibited"]
ComparisonResult = Literal["NEW", "DUPLICATE", "MERGE", "CONFLICT", "REJECT"]

_MEMORY_CATEGORIES = frozenset({"identity", "projects", "preferences", "terms"})


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class MemoryCandidateSourceSpan(CamelModel):
    segment_id: str | None = None
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "MemoryCandidateSourceSpan":
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class MemoryTermCandidate(CamelModel):
    text: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    definition: str | None = Field(None, max_length=4000)


class MemoryCandidate(CamelModel):
    candidate_id: str | None = Field(None, max_length=128)
    category: MemoryCategory
    label: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=16000)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    sensitivity: Sensitivity = "normal"
    sensitive_type: str | None = Field(None, max_length=64)
    sensitive_reason: str | None = Field(None, max_length=1000)
    source_spans: list[MemoryCandidateSourceSpan] = Field(
        default_factory=list, max_length=50
    )
    term: MemoryTermCandidate | None = None

    @model_validator(mode="after")
    def term_only_for_term_category(self) -> "MemoryCandidate":
        if self.term is not None and self.category != "terms":
            raise ValueError("term is only allowed for category 'terms'")
        return self


class MemoryCandidateSource(CamelModel):
    type: Literal["manual_text", "manual_audio", "import_file", "memory_supplement"]
    source_id: str | None = Field(None, max_length=255)
    # Callers may serialize an unused input as an empty string. The model-level
    # validator below still requires at least one non-blank text/OSS URL.
    text: str | None = Field(None, max_length=200000)
    oss_url: str | None = Field(None, max_length=4096)

    @model_validator(mode="after")
    def content_source_required(self) -> "MemoryCandidateSource":
        has_text = bool(self.text and self.text.strip())
        has_oss_url = bool(self.oss_url and self.oss_url.strip())
        if not has_text and not has_oss_url:
            raise ValueError("source must contain text or ossUrl")
        return self


class MemoryCandidateExtractOptions(CamelModel):
    atomic: bool = True
    detect_sensitivity: bool = True
    extract_terms: bool = True


class MemoryCandidateExtractRequest(CamelModel):
    request_id: str = Field(default_factory=new_request_id, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=255)
    scene: Literal["memory_add", "memory_supplement"] = "memory_add"
    source: MemoryCandidateSource
    language: str = Field("zh-CN", min_length=2, max_length=32)
    category_schema_version: str = Field("m13-v1", max_length=32)
    allowed_categories: list[MemoryCategory] = Field(
        default_factory=lambda: ["identity", "projects", "preferences", "terms"],
        min_length=1,
        max_length=4,
    )
    options: MemoryCandidateExtractOptions = Field(default_factory=MemoryCandidateExtractOptions)

    @field_validator("allowed_categories")
    @classmethod
    def categories_must_be_unique(cls, value: list[MemoryCategory]) -> list[MemoryCategory]:
        if len(value) != len(set(value)) or not set(value).issubset(_MEMORY_CATEGORIES):
            raise ValueError("allowedCategories must contain unique M13 categories")
        return value


class MemoryCandidateRejected(CamelModel):
    content: str = Field(..., max_length=16000)
    reason: str = Field(..., min_length=1, max_length=1000)


class MemoryCandidateExtractResponse(CamelModel):
    request_id: str
    model_version: str
    category_schema_version: str
    candidates: list[MemoryCandidate] = Field(default_factory=list)
    rejected: list[MemoryCandidateRejected] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExistingMemoryItem(CamelModel):
    item_id: str = Field(..., min_length=1, max_length=255)
    version: int | None = Field(None, ge=1)
    category: str | None = Field(None, max_length=255)
    content: str = Field(..., min_length=1, max_length=16000)


class MemoryCandidateCompareRequest(CamelModel):
    request_id: str = Field(default_factory=new_request_id, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=255)
    candidate: MemoryCandidate
    namespace_type: str = Field("user", max_length=64)
    namespace_id: str = Field("default", max_length=255)
    candidate_limit: int = Field(40, ge=1, le=100)
    language: str = Field("zh-CN", min_length=2, max_length=32)


class MemoryMergePreview(CamelModel):
    content: str = Field(..., min_length=1, max_length=16000)
    base_item_id: str
    base_version: int | None = Field(None, ge=1)


class MemoryCandidateCompareResponse(CamelModel):
    request_id: str
    model_version: str
    result: ComparisonResult
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_item_ids: list[str] = Field(default_factory=list)
    reason_code: str = Field(..., max_length=128)
    display_reason: str = Field(..., max_length=1000)
    merge_preview: MemoryMergePreview | None = None
