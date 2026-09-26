"""MemoryEngine V2 atomic Claim and policy-first retrieval client."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

import httpx

from memory_engine_sdk.models import LLM
from memory_engine_sdk.transport import headers, v2_base_url

MemoryScope = Literal["self", "cross", "all"]


def _payload(value: Any) -> Any:
  if is_dataclass(value):
    value = asdict(value)
  if isinstance(value, dict):
    return {key: _payload(item) for key, item in value.items() if item is not None}
  if isinstance(value, (list, tuple)):
    return [_payload(item) for item in value]
  return value


def _llm_payload(llm: LLM | None) -> dict[str, Any] | None:
  return _payload(llm) if llm is not None else None


@dataclass(frozen=True)
class MemoryNamespace:
  type: str
  id: str
  label: str | None = None


@dataclass
class MemoryAccessPolicy:
  allowed_modules: list[str] = field(default_factory=lambda: ["*"])
  allowed_scenarios: list[str] = field(default_factory=lambda: ["*"])
  allowed_scopes: list[MemoryScope] = field(default_factory=lambda: ["self"])
  allowed_roles: list[str] = field(default_factory=lambda: ["*"])
  sensitivity: Literal["public", "internal", "sensitive"] = "internal"
  allow_llm: bool = True


@dataclass
class MemorySourceEvent:
  source_type: str
  event_id: str | None = None
  source_id: str | None = None
  meeting_id: str | None = None
  segment_id: str | None = None
  speaker_id: str | None = None
  speaker_role: str | None = None
  raw_text: str | None = None
  occurred_at: str | None = None


@dataclass
class MemoryClaim:
  dimension: str
  claim_type: str
  claim_key: str
  value: Any
  text: str
  fact_status: str = "stated"
  confidence: float = 1.0
  importance: int = 3
  access_policy: MemoryAccessPolicy | None = None
  effective_at: str | None = None
  expires_at: str | None = None


@dataclass(frozen=True)
class MemoryUsageContext:
  module_id: str
  scenario: str
  namespace: MemoryNamespace
  caller_role: str
  scope: MemoryScope = "self"
  current_meeting_id: str | None = None


@dataclass
class MemoryCurrentClaim:
  dimension: str
  claim_key: str | None = None
  value: Any = None
  text: str = ""
  fact_status: str = "stated"


@dataclass
class MemoryCurrentContext:
  meeting_id: str | None = None
  raw_text: str = ""
  claims: list[MemoryCurrentClaim] = field(default_factory=list)


@dataclass
class MemoryUpdateDecision:
  action: str
  reason: str
  claim_id: str | None = None
  previous_claim_id: str | None = None
  lifecycle_status: str | None = None


@dataclass
class MemoryIngestResult:
  event_id: str
  decisions: list[MemoryUpdateDecision]


@dataclass
class MemoryBundleItem:
  claim_id: str
  dimension: str
  claim_type: str
  text: str
  value: Any
  fact_status: str
  score: float
  usage: str | None = None
  reason: str | None = None
  provenance: list[dict[str, Any]] = field(default_factory=list)
  relation_to_current: str = "increment"
  usage_mode: str = "authorized_background_only"
  allowed_action: str = "append_background"


@dataclass
class MemoryBundle:
  bundle_id: str
  items: list[MemoryBundleItem]
  excluded: dict[str, int]
  token_count: int
  method: str
  profile_id: str | None = None
  profile_version: int | None = None
  selected_claim_ids: list[str] = field(default_factory=list)
  dropped_current_duplicate_claim_ids: list[str] = field(default_factory=list)
  dropped_redundant_claim_ids: list[str] = field(default_factory=list)
  conflicting_claim_ids: list[str] = field(default_factory=list)
  effective_injection_count: int = 0
  no_hit_reason: str | None = None
  policy_version: str = "request.v1"
  claim_schema_version: str = "memory-claim-v2"
  expires_at: str = ""
  retrieval_trace: dict[str, Any] = field(default_factory=dict)

  def render_text(self) -> str:
    """Render authorized bundle items for a caller-managed prompt."""
    return "\n".join(f"- [{item.dimension}] {item.text}" for item in self.items)


class Memory:
  """V2 SDK. V1 ``Data`` remains available for staged migration and rollback."""

  @staticmethod
  def ingest(
    user_id: str,
    namespace: MemoryNamespace,
    source_event: MemorySourceEvent,
    claims: list[MemoryClaim],
    *,
    timeout: float = 120.0,
  ) -> MemoryIngestResult:
    response = httpx.post(
      f"{v2_base_url()}/memory/ingest",
      json=_payload(
        {
          "user_id": user_id,
          "namespace": namespace,
          "source_event": source_event,
          "claims": claims,
        }
      ),
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    return MemoryIngestResult(
      event_id=str(data.get("event_id") or ""),
      decisions=[MemoryUpdateDecision(**item) for item in data.get("decisions") or []],
    )

  @staticmethod
  def retrieve(
    user_id: str,
    query: str,
    usage_context: MemoryUsageContext,
    *,
    required_dimensions: list[str] | None = None,
    method: Literal["EXACT", "SEMANTIC", "HYBRID", "LLM"] = "SEMANTIC",
    top_k: int = 8,
    candidate_limit: int = 40,
    max_tokens: int = 1500,
    min_score: float = 0.5,
    llm: LLM | None = None,
    rule_name: str | None = None,
    current_context: MemoryCurrentContext | None = None,
    timeout: float = 120.0,
  ) -> MemoryBundle:
    body = {
      "user_id": user_id,
      "query": query,
      "required_dimensions": required_dimensions or [],
      "method": method,
      "usage_context": usage_context,
      "top_k": top_k,
      "candidate_limit": candidate_limit,
      "max_tokens": max_tokens,
      "min_score": min_score,
      "llm": _llm_payload(llm),
      "rule_name": rule_name,
      "current_context": current_context,
    }
    response = httpx.post(
      f"{v2_base_url()}/memory/retrieve",
      json=_payload(body),
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    return MemoryBundle(
      bundle_id=str(data.get("bundle_id") or ""),
      items=[MemoryBundleItem(**item) for item in data.get("items") or []],
      excluded=data.get("excluded") or {},
      token_count=int(data.get("token_count") or 0),
      method=str(data.get("method") or method),
      profile_id=data.get("profile_id"),
      profile_version=data.get("profile_version"),
      selected_claim_ids=list(data.get("selected_claim_ids") or []),
      dropped_current_duplicate_claim_ids=list(
        data.get("dropped_current_duplicate_claim_ids") or []
      ),
      dropped_redundant_claim_ids=list(data.get("dropped_redundant_claim_ids") or []),
      conflicting_claim_ids=list(data.get("conflicting_claim_ids") or []),
      effective_injection_count=int(data.get("effective_injection_count") or 0),
      no_hit_reason=data.get("no_hit_reason"),
      policy_version=str(data.get("policy_version") or "request.v1"),
      claim_schema_version=str(data.get("claim_schema_version") or "memory-claim-v2"),
      expires_at=str(data.get("expires_at") or ""),
      retrieval_trace=dict(data.get("retrieval_trace") or {}),
    )

  @staticmethod
  def call(
    bundle_id: str,
    module_id: str,
    prompt_template: str,
    *,
    slot: str = "<memory_context>",
    use_llm: bool = False,
    llm: LLM | None = None,
    timeout: float = 120.0,
  ) -> str:
    response = httpx.post(
      f"{v2_base_url()}/memory/call",
      json=_payload(
        {
          "bundle_id": bundle_id,
          "module_id": module_id,
          "prompt_template": prompt_template,
          "slot": slot,
          "use_llm": use_llm,
          "llm": _llm_payload(llm),
        }
      ),
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()
    return str((response.json().get("data") or {}).get("result") or "")

  @staticmethod
  def history(claim_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    response = httpx.get(
      f"{v2_base_url()}/memory/claims/{claim_id}/history",
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("data") or {}

  @staticmethod
  def revoke(claim_id: str, reason: str, *, timeout: float = 30.0) -> None:
    response = httpx.post(
      f"{v2_base_url()}/memory/claims/{claim_id}/revoke",
      json={"reason": reason},
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()

  @staticmethod
  def resolve(
    claim_id: str,
    resolution: Literal["ACCEPT", "REJECT"],
    reason: str,
    *,
    timeout: float = 30.0,
  ) -> None:
    response = httpx.post(
      f"{v2_base_url()}/memory/claims/{claim_id}/resolve",
      json={"resolution": resolution, "reason": reason},
      headers=headers(),
      timeout=timeout,
    )
    response.raise_for_status()
