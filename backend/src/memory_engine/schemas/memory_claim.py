"""P0/P1 structured memory claim, policy, and bundle schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from memory_engine.schemas.memory_field import LLMConfig


FactStatus = Literal[
    "stated", "decision", "commitment", "proposal", "forecast", "opinion", "correction"
]
LifecycleStatus = Literal["active", "pending", "conflicted", "superseded", "revoked"]
MemoryScope = Literal["self", "cross", "all"]


class MemoryNamespace(BaseModel):
    """Hard isolation boundary, such as a financing deal or product project."""

    type: str = Field(..., min_length=1, max_length=64)
    id: str = Field(..., min_length=1, max_length=255)
    label: str | None = Field(None, max_length=255)


class MemoryProvenance(BaseModel):
    """Evidence pointer for one claim."""

    source_type: str = Field(..., min_length=1, max_length=32)
    source_id: str | None = Field(None, max_length=255)
    meeting_id: str | None = Field(None, max_length=255)
    segment_id: str | None = Field(None, max_length=255)
    speaker_id: str | None = Field(None, max_length=255)
    speaker_role: str | None = Field(None, max_length=128)
    evidence: str | None = Field(None, max_length=8000)
    occurred_at: str | None = None


class MemoryAccessPolicy(BaseModel):
    """Data-level usage permission, evaluated before any LLM sees a claim."""

    allowed_modules: list[str] = Field(default_factory=lambda: ["*"])
    allowed_scenarios: list[str] = Field(default_factory=lambda: ["*"])
    allowed_scopes: list[MemoryScope] = Field(default_factory=lambda: ["self"])
    allowed_roles: list[str] = Field(default_factory=lambda: ["*"])
    sensitivity: Literal["public", "internal", "sensitive"] = "internal"
    allow_llm: bool = True


class MemoryClaimInput(BaseModel):
    """One atomic memory candidate supplied by parse/SDK/meeting pipelines."""

    dimension: str = Field(..., min_length=1, max_length=255)
    claim_type: str = Field(..., min_length=1, max_length=128)
    claim_key: str = Field(..., min_length=1, max_length=255)
    value: Any
    text: str = Field(..., min_length=1, max_length=16000)
    fact_status: FactStatus = "stated"
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    importance: int = Field(3, ge=1, le=5)
    access_policy: MemoryAccessPolicy | None = None
    effective_at: str | None = None
    expires_at: str | None = None


class MemorySourceEventInput(BaseModel):
    """Immutable source event metadata shared by claims in one ingest."""

    event_id: str | None = Field(None, max_length=255)
    source_type: str = Field(..., min_length=1, max_length=32)
    source_id: str | None = Field(None, max_length=255)
    meeting_id: str | None = Field(None, max_length=255)
    segment_id: str | None = Field(None, max_length=255)
    speaker_id: str | None = Field(None, max_length=255)
    speaker_role: str | None = Field(None, max_length=128)
    raw_text: str | None = Field(None, max_length=200000)
    occurred_at: str | None = None


class MemoryIngestRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=255)
    namespace: MemoryNamespace
    source_event: MemorySourceEventInput
    claims: list[MemoryClaimInput] = Field(..., min_length=1, max_length=200)


class MemoryUpdateDecision(BaseModel):
    action: Literal["ADD", "CONFIRM", "UPDATE", "SUPERSEDE", "CONFLICT", "REJECT", "NOOP"]
    claim_id: str | None = None
    previous_claim_id: str | None = None
    reason: str
    lifecycle_status: LifecycleStatus | None = None


class MemoryIngestResult(BaseModel):
    event_id: str
    decisions: list[MemoryUpdateDecision]


class MemoryUsageContext(BaseModel):
    module_id: str = Field(..., min_length=1, max_length=255)
    scenario: str = Field(..., min_length=1, max_length=255)
    scope: MemoryScope = "self"
    current_meeting_id: str | None = Field(None, max_length=255)
    namespace: MemoryNamespace
    caller_role: str = Field(..., min_length=1, max_length=128)


class MemoryCurrentClaim(BaseModel):
    """Structured fact already present in the current consumer context."""

    dimension: str = Field(..., min_length=1, max_length=255)
    claim_key: str | None = Field(None, max_length=255)
    value: Any = None
    text: str = Field("", max_length=16000)
    fact_status: FactStatus = "stated"


class MemoryCurrentContext(BaseModel):
    """Current-meeting evidence used only for duplicate/conflict classification."""

    meeting_id: str | None = Field(None, max_length=255)
    raw_text: str = Field("", max_length=200000)
    claims: list[MemoryCurrentClaim] = Field(default_factory=list, max_length=200)


class MemoryRetrieveV2Request(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=255)
    query: str = Field("", max_length=16000)
    required_dimensions: list[str] = Field(default_factory=list, max_length=100)
    method: Literal["EXACT", "SEMANTIC", "HYBRID", "LLM"] = "SEMANTIC"
    usage_context: MemoryUsageContext
    top_k: int = Field(8, ge=1, le=50)
    candidate_limit: int = Field(40, ge=1, le=200)
    max_tokens: int = Field(1500, ge=100, le=16000)
    min_score: float = Field(0.5, ge=0.0, le=1.0)
    llm: LLMConfig | None = None
    rule_name: str | None = Field(None, min_length=1, max_length=128)
    current_context: MemoryCurrentContext | None = None

    @model_validator(mode="after")
    def namespace_must_match(self) -> "MemoryRetrieveV2Request":
        if not self.usage_context.namespace.id.strip():
            raise ValueError("usage_context.namespace is required")
        return self


class MemoryBundleItem(BaseModel):
    claim_id: str
    dimension: str
    claim_type: str
    text: str
    value: Any
    fact_status: FactStatus
    score: float
    usage: str | None = None
    reason: str | None = None
    provenance: list[MemoryProvenance] = Field(default_factory=list)
    relation_to_current: Literal["increment", "duplicate", "conflict"] = "increment"
    usage_mode: str = "authorized_background_only"
    allowed_action: Literal["append_background", "report_conflict", "drop"] = "append_background"


class MemoryBundleOut(BaseModel):
    bundle_id: str
    items: list[MemoryBundleItem]
    excluded: dict[str, int]
    token_count: int
    method: str
    profile_id: str | None = None
    profile_version: int | None = None
    selected_claim_ids: list[str] = Field(default_factory=list)
    dropped_current_duplicate_claim_ids: list[str] = Field(default_factory=list)
    dropped_redundant_claim_ids: list[str] = Field(default_factory=list)
    conflicting_claim_ids: list[str] = Field(default_factory=list)
    effective_injection_count: int = 0
    no_hit_reason: str | None = None
    policy_version: str = "request.v1"
    claim_schema_version: str = "memory-claim-v2"
    expires_at: str
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)


class MemoryCallV2Request(BaseModel):
    bundle_id: str = Field(..., min_length=1, max_length=255)
    module_id: str = Field(..., min_length=1, max_length=255)
    prompt_template: str = Field(..., max_length=100000)
    slot: str = "<memory_context>"
    use_llm: bool = False
    llm: LLMConfig | None = None


class MemoryCallV2Response(BaseModel):
    result: str
    filled_prompt: str
    bundle_id: str


class MemoryClaimHistoryOut(BaseModel):
    identity_id: str
    items: list[dict[str, Any]]


class MemoryClaimRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000)


class MemoryClaimResolveRequest(BaseModel):
    resolution: Literal["ACCEPT", "REJECT"]
    reason: str = Field(..., min_length=1, max_length=1000)
