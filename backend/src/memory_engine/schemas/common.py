"""Shared Pydantic schemas."""

from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


class SearchMode(StrEnum):
    """Schema/data search modes."""

    EXACT = "EXACT"
    REGEX = "REGEX"
    SEMANTIC = "SEMANTIC"
    LLM = "LLM"


class ApiResponse(BaseModel):
    """Standard API envelope."""

    code: int = 0
    message: str = "ok"
    data: Any = None


T = TypeVar("T")


class PageParams(BaseModel):
    """Pagination."""

    offset: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=200)
