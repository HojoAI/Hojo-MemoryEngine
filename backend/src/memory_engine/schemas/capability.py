"""Capability registry API schemas."""

from typing import Any

from pydantic import BaseModel, Field


class CapabilityRegisterBody(BaseModel):
    """Register or update a runtime capability (SDK / API)."""

    capability_name: str = Field(..., max_length=128)
    module_name: str = Field(..., max_length=255, description="Python module path")
    service_name: str = Field(..., max_length=128, description="Callable name in module")
    rule_kind: str = Field(..., pattern="^(parse|retrieve|call)$")
    slot_name: str | None = Field(None, max_length=128)
    config_json: dict[str, Any] | None = None
    code_fingerprint: str | None = Field(None, max_length=64)
    enabled: int = 1


class CapabilityHeartbeatBody(BaseModel):
    """SDK heartbeat for capability liveness."""

    capability_name: str
    rule_kind: str = Field(..., pattern="^(parse|retrieve|call)$")
    code_fingerprint: str | None = None


class CapabilityOut(BaseModel):
    """Capability registry response."""

    id: int
    tenant_id: int
    org_id: int
    capability_name: str
    module_name: str
    service_name: str
    rule_kind: str
    slot_name: str | None = None
    config_json: dict[str, Any] | None = None
    enabled: int = 1
    last_seen_time: str | None = None
    heartbeat_version: int = 0
    code_fingerprint: str | None = None
    version: int = 1

    model_config = {"from_attributes": True}
