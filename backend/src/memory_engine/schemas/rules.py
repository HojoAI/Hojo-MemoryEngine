"""Parse / retrieve / call rule API schemas."""

from typing import Any

from pydantic import BaseModel, Field


class RuleCreateBody(BaseModel):
    """Shared fields for rule create."""

    rule_name: str = Field(..., max_length=128)
    rule_config_json: dict[str, Any] | None = None
    capability_id: int | None = None
    capability_name: str | None = Field(None, max_length=128)
    module_name: str | None = Field(None, max_length=255)
    service_name: str | None = Field(None, max_length=128)
    code_fingerprint: str | None = Field(None, max_length=64)
    priority: int = 0


class ParseRuleCreate(RuleCreateBody):
    """Create parse rule."""

    memory_field_name: str


class MergeRuleCreate(RuleCreateBody):
    """Create merge rule (LLM fusion for MERGE match_method)."""

    memory_field_name: str


class RetrieveRuleCreate(RuleCreateBody):
    """Create retrieve rule."""

    memory_field_name: str | None = None
    retrieve_method: str = "EXACT"


class CallRuleCreate(RuleCreateBody):
    """Create call rule."""

    memory_field_name: str
    slot_name: str = Field(..., max_length=128)


class RuleUpdateBody(BaseModel):
    """Update rule (new version)."""

    rule_config_json: dict[str, Any] | None = None
    capability_id: int | None = None
    priority: int | None = None
    retrieve_method: str | None = None
    slot_name: str | None = None


class RuleOut(BaseModel):
    """Rule response."""

    id: int
    rule_name: str
    version: int
    memory_field_name: str | None = None
    retrieve_method: str | None = None
    slot_name: str | None = None
    rule_config_json: dict[str, Any] | None = None
    priority: int = 0

    model_config = {"from_attributes": True}
