"""Agent Memory Leaderboard Add/Search contract schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AMLMessage(BaseModel):
    role: Literal["user", "assistant"]
    timestamp: int | None = Field(default=None, ge=0)
    content: str = Field(..., min_length=1, max_length=200_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class AMLAddRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=512)
    messages: list[AMLMessage] = Field(..., min_length=1, max_length=100)
    user_id: str = Field(..., min_length=1, max_length=512)
    session_id: str = Field(..., min_length=1, max_length=512)


class AMLAddResponse(BaseModel):
    success: Literal[True] = True
    request_id: str
    user_id: str
    session_id: str


class AMLSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100_000)
    options: list[str] | None = Field(default=None, max_length=100)
    user_id: str = Field(..., min_length=1, max_length=512)
    top_k: int = Field(..., ge=1, le=100)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("options")
    @classmethod
    def options_must_not_contain_blanks(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("options must not contain blank values")
        return value


class AMLSearchItem(BaseModel):
    id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    score: float | None = None
    created_at: str | None = None


class AMLSearchResponse(BaseModel):
    data: list[AMLSearchItem]


class AMLClearRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=512)


class AMLClearResponse(BaseModel):
    success: Literal[True] = True
    user_id: str
    deleted_units: int
    deleted_requests: int
