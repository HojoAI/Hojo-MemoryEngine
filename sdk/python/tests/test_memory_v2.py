"""MemoryOS V2 SDK request and response contract tests."""

from unittest.mock import MagicMock

import pytest

from memory_engine_sdk import (
    Memory,
    MemoryAccessPolicy,
    MemoryClaim,
    MemoryCurrentClaim,
    MemoryCurrentContext,
    MemoryNamespace,
    MemorySourceEvent,
    MemoryUsageContext,
)
from memory_engine_sdk import memory_v2
from memory_engine_sdk.transport import v2_base_url


def _response(data):
  response = MagicMock()
  response.json.return_value = {"data": data}
  response.raise_for_status.return_value = None
  return response


def test_v2_base_url_derived_from_v1(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("MEMORY_ENGINE_API_BASE", "https://memory.example/api/v1")
  monkeypatch.delenv("MEMORY_ENGINE_API_V2_BASE", raising=False)
  assert v2_base_url() == "https://memory.example/api/v2"


def test_ingest_serializes_namespace_provenance_and_policy(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  captured = {}

  def post(url, **kwargs):
    captured.update(url=url, **kwargs)
    return _response(
      {
        "event_id": "event-1",
        "decisions": [{"action": "ADD", "reason": "new", "claim_id": "claim-1"}],
      }
    )

  monkeypatch.setattr(memory_v2.httpx, "post", post)
  result = Memory.ingest(
    "user-1",
    MemoryNamespace("financing_project", "deal-1"),
    MemorySourceEvent("meeting", meeting_id="meeting-1", raw_text="证据"),
    [
      MemoryClaim(
        dimension="stated_figures",
        claim_type="metric",
        claim_key="arr",
        value={"amount": 1000, "currency": "CNY"},
        text="ARR 为 1000 万元",
        access_policy=MemoryAccessPolicy(
          allowed_modules=["MeetingPitfallAnalysis"], allowed_scopes=["cross"]
        ),
      )
    ],
  )
  assert captured["url"].endswith("/api/v2/memory/ingest")
  assert captured["json"]["namespace"]["id"] == "deal-1"
  assert captured["json"]["source_event"]["meeting_id"] == "meeting-1"
  assert captured["json"]["claims"][0]["access_policy"]["allowed_scopes"] == ["cross"]
  assert result.decisions[0].claim_id == "claim-1"


def test_retrieve_returns_renderable_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
  captured = {}

  def post(url, **kwargs):
    captured.update(url=url, **kwargs)
    assert kwargs["json"]["usage_context"]["module_id"] == "MeetingDetailedSummary"
    return _response(
      {
        "bundle_id": "bundle-1",
        "items": [
          {
            "claim_id": "claim-1",
            "dimension": "meeting_thread",
            "claim_type": "decision",
            "text": "下一轮补充财务材料",
            "value": "下一轮补充财务材料",
            "fact_status": "commitment",
            "score": 0.91,
          }
        ],
        "excluded": {},
        "token_count": 12,
        "method": "LLM",
        "policy_version": "meeting.investment.MeetingDetailedSummary.v1@3",
        "claim_schema_version": "memory-claim-v2",
        "expires_at": "2026-09-20T12:00:00+00:00",
        "retrieval_trace": {"raw_claim_count": 5, "selected_count": 1},
      }
    )

  monkeypatch.setattr(memory_v2.httpx, "post", post)
  bundle = Memory.retrieve(
    "user-1",
    "总结融资进展",
    MemoryUsageContext(
      module_id="MeetingDetailedSummary",
      scenario="financing",
      namespace=MemoryNamespace("financing_project", "deal-1"),
      caller_role="investor",
      scope="cross",
      current_meeting_id="meeting-2",
    ),
    method="LLM",
    rule_name="meeting.investment.MeetingDetailedSummary.v1",
    current_context=MemoryCurrentContext(
      meeting_id="meeting-2",
      raw_text="本场融资目标为4000万元",
      claims=[
        MemoryCurrentClaim(
          dimension="financing_target", claim_key="amount", value=4000
        )
      ],
    ),
  )
  assert bundle.bundle_id == "bundle-1"
  assert "下一轮补充财务材料" in bundle.render_text()
  assert captured["json"]["rule_name"] == "meeting.investment.MeetingDetailedSummary.v1"
  assert captured["json"]["current_context"]["claims"][0]["claim_key"] == "amount"
  assert bundle.policy_version.endswith("@3")
  assert bundle.retrieval_trace["raw_claim_count"] == 5
