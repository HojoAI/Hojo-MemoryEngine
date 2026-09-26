"""P0 retrieval safety and no-random-fallback tests."""

import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from memory_engine.schemas.memory_claim import (
    MemoryCallV2Request,
    MemoryCurrentClaim,
    MemoryCurrentContext,
    MemoryNamespace,
    MemoryRetrieveV2Request,
    MemoryUsageContext,
)
from memory_engine.services import memory_v2_retrieve


def test_time_scoped_query_enables_history_only_when_explicit() -> None:
    assert memory_v2_retrieve._query_requests_history(
        "What changed between 2024-11-01 and 2025-01-21?"
    )
    assert not memory_v2_retrieve._query_requests_history(
        "What are the qualifications of Johnny during code review?"
    )


@pytest.mark.parametrize(
    "query",
    [
        "How many plants did I acquire in the last month?",
        "How much have I spent since the start of the year?",
        "What time did I go to bed on the day before my appointment?",
    ],
)
def test_natural_language_time_scope_enables_history(query: str) -> None:
    assert memory_v2_retrieve._query_requests_history(query)


@pytest.mark.parametrize(
    "query",
    [
        "How has my preferred coffee changed over time?",
        "What did I use to do before moving to Seattle?",
        "Which subscription do I no longer use?",
    ],
)
def test_change_queries_enable_version_history(query: str) -> None:
    assert memory_v2_retrieve._query_requests_history(query)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("What was my status on Feb 15, 2035?", "2035-02-15"),
        ("Did I launch it in May 2035?", "2035-05"),
        ("What happened on 2035-09-15?", "2035-09-15"),
    ],
)
def test_human_readable_dates_enable_history_and_are_normalized(query: str, expected: str) -> None:
    assert memory_v2_retrieve._query_requests_history(query)
    assert expected in memory_v2_retrieve._query_date_tokens(query)


def test_human_readable_date_matches_iso_provenance() -> None:
    claim = {"provenance": [{"occurred_at": "2035-02-15T12:00:00+00:00"}]}

    assert memory_v2_retrieve._claim_matches_query_date(
        "What was my status on Feb 15, 2035?", claim
    )


def test_human_readable_as_of_date_builds_snapshot_cutoff() -> None:
    assert memory_v2_retrieve._as_of_cutoff(
        "What is my current status as of September 15, 2035?"
    ) == datetime(2035, 9, 16, tzinfo=timezone.utc)


def test_human_readable_on_date_builds_snapshot_cutoff() -> None:
    assert memory_v2_retrieve._as_of_cutoff(
        "What was my employment status on Feb 15, 2035?"
    ) == datetime(2035, 2, 16, tzinfo=timezone.utc)


def test_multifacet_queries_expand_compound_aggregation() -> None:
    facets = memory_v2_retrieve._retrieval_query_facets(
        "How many model kits have I worked on or bought?", max_queries=4
    )

    assert facets[0] == "How many model kits have I worked on or bought?"
    assert "model kits worked" in facets
    assert "model kits bought" in facets


def test_simple_query_does_not_expand_into_facets() -> None:
    assert memory_v2_retrieve._retrieval_query_facets("What is my cat's name?", max_queries=4) == [
        "What is my cat's name?"
    ]


def test_facet_coverage_promotes_specialist_candidates_without_dropping_fallbacks() -> None:
    general = {"claim_id": "general", "_score": 0.95, "_query_facets": {0}}
    duplicate_general = {"claim_id": "general-2", "_score": 0.90, "_query_facets": {0}}
    worked = {"claim_id": "worked", "_score": 0.75, "_query_facets": {1}}
    bought = {"claim_id": "bought", "_score": 0.70, "_query_facets": {2}}

    ordered, promoted = memory_v2_retrieve._prioritize_query_facet_coverage(
        [general, duplicate_general, worked, bought], facet_count=3
    )

    assert [claim["claim_id"] for claim in ordered] == ["general", "worked", "bought", "general-2"]
    assert promoted == 2


def test_claim_date_match_uses_provenance_occurrence() -> None:
    claim = {"provenance": [{"occurred_at": "2024-11-05T12:00:00+00:00"}]}
    assert memory_v2_retrieve._claim_matches_query_date("What happened on 2024-11-05?", claim)


def test_aggregation_shortlist_includes_independent_sessions() -> None:
    claims = [
        {"claim_id": f"a-{index}", "provenance": [{"meeting_id": "session-a"}]}
        for index in range(6)
    ] + [
        {"claim_id": "b-1", "provenance": [{"meeting_id": "session-b"}]},
        {"claim_id": "c-1", "provenance": [{"meeting_id": "session-c"}]},
    ]
    shortlist = memory_v2_retrieve._aggregation_rerank_shortlist(claims, 4)
    assert [claim["claim_id"] for claim in shortlist] == ["a-0", "a-1", "b-1", "c-1"]


def test_aggregation_compaction_preserves_numeric_operand() -> None:
    text = (
        "I discussed my model kits in general. "
        "The model kits are something I enjoy. "
        "I have 7 model kits in the cabinet."
    )
    compact = memory_v2_retrieve._compact_aggregation_text(
        text, "How many model kits do I have?", 50
    )
    assert "7 model kits" in compact


def test_as_of_snapshot_excludes_future_and_superseded_versions() -> None:
    cutoff = memory_v2_retrieve._as_of_cutoff("What was my plan as of 2024-02-01?")
    assert cutoff == datetime(2024, 2, 2, tzinfo=timezone.utc)
    assert (
        memory_v2_retrieve._claim_as_of_exclusion(
            {"provenance": [{"occurred_at": "2024-03-01T00:00:00Z"}]}, cutoff
        )
        == "future"
    )
    assert (
        memory_v2_retrieve._claim_as_of_exclusion(
            {
                "provenance": [{"occurred_at": "2024-01-01T00:00:00Z"}],
                "superseded_at": "2024-01-20T00:00:00Z",
            },
            cutoff,
        )
        == "superseded"
    )
    assert (
        memory_v2_retrieve._claim_as_of_exclusion(
            {
                "provenance": [{"occurred_at": "2024-01-01T00:00:00Z"}],
                "superseded_at": "2024-02-10T00:00:00Z",
            },
            cutoff,
        )
        is None
    )
    assert (
        memory_v2_retrieve._as_of_cutoff("What happened between 2024-01-01 and 2024-02-01?") is None
    )


def _body(method: str = "SEMANTIC", min_score: float = 0.9) -> MemoryRetrieveV2Request:
    return MemoryRetrieveV2Request(
        user_id="user-1",
        query="融资估值",
        method=method,
        min_score=min_score,
        usage_context=MemoryUsageContext(
            module_id="meeting_summary",
            scenario="financing",
            scope="cross",
            current_meeting_id="meeting-2",
            namespace=MemoryNamespace(type="financing_project", id="deal-1"),
            caller_role="investor",
        ),
    )


def _claim() -> dict:
    return {
        "claim_id": "claim-1",
        "dimension": "product_name",
        "claim_type": "name",
        "claim_key": "office_location",
        "text": "办公地点在上海",
        "value": "上海",
        "fact_status": "stated",
        "importance": 3,
        "namespace": {"type": "financing_project", "id": "deal-1"},
        "lifecycle_status": "active",
        "is_current": True,
        "access_policy": {
            "allowed_modules": ["*"],
            "allowed_scenarios": ["*"],
            "allowed_scopes": ["cross"],
            "allowed_roles": ["*"],
            "sensitivity": "internal",
            "allow_llm": True,
        },
        "provenance": [{"source_type": "meeting", "meeting_id": "meeting-1"}],
    }


@pytest.mark.asyncio
async def test_v2_profile_overrides_caller_retrieval_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_rule(*args, **kwargs):
        return SimpleNamespace(
            rule_name="meeting.investment.MeetingDetailedSummary.v1",
            retrieve_method="LLM",
            version=3,
            rule_config_json={
                "required_dimensions": ["financing_project_facts"],
                "top_k": 3,
                "max_tokens": 500,
                "min_score": 0.6,
                "max_increment_items": 2,
                "usage_mode": "history_comparison_only",
            },
        )

    monkeypatch.setattr(memory_v2_retrieve.rule_service, "get_active_retrieve", get_rule)
    body = _body().model_copy(update={"rule_name": "meeting.investment.MeetingDetailedSummary.v1"})
    resolved, profile_id, version, profile = await memory_v2_retrieve._resolve_profile(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert resolved.method == "LLM"
    assert resolved.required_dimensions == ["financing_project_facts"]
    assert resolved.top_k == 3
    assert resolved.max_tokens == 500
    assert resolved.min_score == 0.6
    assert profile_id == body.rule_name
    assert version == 3
    assert profile["max_increment_items"] == 2


@pytest.mark.asyncio
async def test_invalid_v2_profile_returns_domain_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_rule(*args, **kwargs):
        return SimpleNamespace(
            rule_name="meeting.invalid",
            retrieve_method="SEMANTIC",
            version=1,
            rule_config_json={"top_k": 0},
        )

    monkeypatch.setattr(memory_v2_retrieve.rule_service, "get_active_retrieve", get_rule)
    body = _body().model_copy(update={"rule_name": "meeting.invalid"})
    with pytest.raises(ValidationError) as caught:
        await memory_v2_retrieve._resolve_profile(
            SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
        )
    assert getattr(caught.value, "status_code", None) == 422


def test_current_context_classifies_duplicate_conflict_and_increment() -> None:
    body = _body("EXACT", 0.0).model_copy(
        update={
            "current_context": MemoryCurrentContext(
                meeting_id="meeting-2",
                raw_text="本场确认公司办公地点在上海市浦东新区。",
                claims=[
                    MemoryCurrentClaim(
                        dimension="financing_target",
                        claim_key="amount",
                        value={"amount": 4000},
                        text="本轮融资目标为4000万元",
                    )
                ],
            )
        }
    )
    duplicate = _claim()
    duplicate["text"] = "公司办公地点在上海市浦东新区"
    duplicate["value"] = "上海市浦东新区"
    conflict = {
        **_claim(),
        "dimension": "financing_target",
        "claim_key": "amount",
        "value": {"amount": 3000},
        "text": "历史融资目标为3000万元",
    }
    increment = {
        **_claim(),
        "dimension": "team_profile",
        "claim_key": "founder",
        "value": "张三",
        "text": "创始人为张三",
    }

    assert memory_v2_retrieve._relation_to_current(duplicate, body) == "duplicate"
    assert memory_v2_retrieve._relation_to_current(conflict, body) == "conflict"
    assert memory_v2_retrieve._relation_to_current(increment, body) == "increment"


def test_action_phrase_extraction_only_returns_explicit_query_actions() -> None:
    assert memory_v2_retrieve._action_phrases("Which things do I need to pick up or return?") == [
        "pick up",
        "return",
    ]
    assert memory_v2_retrieve._action_phrases("Who founded the company?") == []


def test_query_term_coverage_matches_irregular_lead_past_tense() -> None:
    query = "How many projects have I led or am currently leading?"
    direct_evidence = "In my Marketing Research class project, I led the data analysis team."

    assert memory_v2_retrieve._query_term_coverage(query, direct_evidence) > 0.5


def test_query_terms_preserve_high_signal_short_temporal_and_medical_words() -> None:
    terms = memory_v2_retrieve._query_recall_terms(
        "What time did I go to bed before my ENT appointment?"
    )

    assert {"bed", "ent"}.issubset(terms)


def test_monetary_evidence_coverage_requires_a_price_and_subject() -> None:
    query = "How much total money have I spent on bike-related expenses?"

    assert (
        memory_v2_retrieve._monetary_evidence_coverage(
            query, "I bought a bike helmet for $120 from the local bike shop."
        )
        == 1.0
    )
    assert (
        memory_v2_retrieve._monetary_evidence_coverage(
            query, "I have ridden my bike 347 miles since the start of the year."
        )
        == 0.0
    )


def test_aggregation_evidence_prefers_scoped_duration_operands() -> None:
    query = "How many hours in total did I spend driving to road trip destinations combined?"

    assert (
        memory_v2_retrieve._aggregation_evidence_coverage(
            query, "I drove for five hours to Tennessee on a road trip."
        )
        > 0
    )
    assert (
        memory_v2_retrieve._aggregation_evidence_coverage(query, "I read five books this month.")
        == 0
    )


def test_user_provenance_is_prioritized_over_assistant_provenance() -> None:
    assert (
        memory_v2_retrieve._evidence_speaker_role({"provenance": [{"speaker_role": "user"}]})
        == "user"
    )
    assert (
        memory_v2_retrieve._evidence_speaker_role({"provenance": [{"speaker_role": "assistant"}]})
        == "assistant"
    )


def test_diversification_prefers_other_sessions_without_dropping_fallbacks() -> None:
    first = {**_claim(), "claim_id": "first", "provenance": [{"meeting_id": "m1"}]}
    same_session = {**_claim(), "claim_id": "same", "provenance": [{"meeting_id": "m1"}]}
    other_session = {**_claim(), "claim_id": "other", "provenance": [{"meeting_id": "m2"}]}

    diversified, deferred = memory_v2_retrieve._diversify_by_evidence_group(
        [first, same_session, other_session], max_per_group=1
    )

    assert [claim["claim_id"] for claim in diversified] == ["first", "other", "same"]
    assert deferred == 1


@pytest.mark.asyncio
async def test_diagnostics_identify_budget_losses_without_logging_claim_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    claims = [
        {**_claim(), "claim_id": "short", "text": "bike"},
        {**_claim(), "claim_id": "large", "text": "bike " + "PRIVATE-CONTENT " * 30},
        {**_claim(), "claim_id": "fallback", "text": "other"},
        {**_claim(), "claim_id": "outside-top-k", "text": "unrelated"},
    ]

    async def list_claims(*args, **kwargs):
        return claims

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(
            memory_v2_bundle_ttl_seconds=3600,
            memory_retrieve_action_recall_enabled=False,
            memory_retrieve_lexical_recall_enabled=False,
            memory_retrieve_evidence_neighbor_enabled=False,
            memory_retrieve_session_diversity_enabled=False,
            memory_retrieve_diagnostics_enabled=True,
            memory_retrieve_diagnostics_max_ids=10,
        ),
    )
    body = _body("EXACT", 0.0).model_copy(update={"query": "bike", "top_k": 2, "max_tokens": 100})

    with caplog.at_level(logging.INFO, logger=memory_v2_retrieve.__name__):
        result = await memory_v2_retrieve.retrieve(
            SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
        )

    messages = [
        record.message.removeprefix("memory retrieval diagnostics ")
        for record in caplog.records
        if record.message.startswith("memory retrieval diagnostics ")
    ]
    assert len(messages) == 1
    detail = json.loads(messages[0])
    assert detail["stages"]["mongo"]["authorized"]["claim_ids"] == [
        "short",
        "large",
        "fallback",
        "outside-top-k",
    ]
    assert detail["selection"]["token_limit"]["items"][0]["claim_id"] == "large"
    assert detail["selection"]["max_items"]["items"][0]["claim_id"] == "outside-top-k"
    assert {item.claim_id for item in result.items} == {"short", "fallback"}
    assert result.retrieval_trace["token_limit_rejected"] == 1
    assert result.retrieval_trace["max_items_rejected"] == 1
    assert "PRIVATE-CONTENT" not in messages[0]


@pytest.mark.asyncio
async def test_retrieve_adds_policy_filtered_evidence_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = {
        **_claim(),
        "claim_id": "seed",
        "text": "I replaced the kitchen faucet.",
        "provenance": [{"source_type": "chat", "source_id": "session-1"}],
    }
    neighbor = {
        **_claim(),
        "claim_id": "neighbor",
        "text": "In the same session, I also fixed the kitchen shelves.",
        "provenance": [{"source_type": "chat", "source_id": "session-1"}],
    }

    async def list_claims(*args, **kwargs):
        return [seed]

    async def list_neighbors(*args, **kwargs):
        assert [claim["claim_id"] for claim in args[4]] == ["seed"]
        return [neighbor]

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(
        memory_v2_retrieve.memory_claim_store,
        "list_current_claim_evidence_neighbors",
        list_neighbors,
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(
            memory_v2_bundle_ttl_seconds=3600,
            memory_retrieve_action_recall_enabled=False,
            memory_retrieve_lexical_recall_enabled=False,
            memory_retrieve_evidence_neighbor_enabled=True,
            memory_retrieve_evidence_neighbor_seed_limit=4,
            memory_retrieve_evidence_neighbor_limit=16,
            memory_retrieve_session_diversity_enabled=True,
            memory_retrieve_session_max_items=2,
        ),
    )

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(),
        RequestContext(tenant_id=1, org_id=2),
        _body("EXACT", 0.0).model_copy(update={"query": "Which kitchen items did I replace?"}),
    )

    assert {item.claim_id for item in result.items} == {"seed", "neighbor"}
    assert result.retrieval_trace["evidence_neighbors_recalled"] == 1


@pytest.mark.asyncio
async def test_retrieve_merges_authorized_action_phrase_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {**_claim(), "claim_id": "base", "text": "办公室在上海"}
    pickup = {
        **_claim(),
        "claim_id": "pickup",
        "text": "我还需要去取干洗店的蓝色西装。",
    }
    returned = {
        **_claim(),
        "claim_id": "return",
        "text": "我需要把不合脚的靴子退回商店。",
    }

    async def list_claims(*args, **kwargs):
        return [base]

    async def list_action_claims(*args, **kwargs):
        assert args[4] == ["pick up", "return"]
        return [pickup, returned]

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(
        memory_v2_retrieve.memory_claim_store,
        "list_current_claims_matching_phrases",
        list_action_claims,
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(
            memory_v2_bundle_ttl_seconds=3600,
            memory_retrieve_action_recall_enabled=True,
            memory_retrieve_action_recall_limit=8,
            memory_retrieve_action_recall_boost=0.12,
            memory_retrieve_lexical_recall_enabled=False,
        ),
    )
    body = _body("EXACT", 0.0).model_copy(update={"query": "What do I need to pick up or return?"})

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert {item.claim_id for item in result.items} >= {"pickup", "return"}


@pytest.mark.asyncio
async def test_retrieve_merges_precise_lexical_candidates_and_emits_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = {**_claim(), "claim_id": "base", "text": "办公室在上海"}
    relevant = {
        **_claim(),
        "claim_id": "expense",
        "text": "自行车链条更换花了25美元，车灯安装花了40美元。",
    }

    async def list_claims(*args, **kwargs):
        return [base]

    async def list_lexical_claims(*args, **kwargs):
        assert {"bike", "expens"}.issubset(args[4])
        return [relevant]

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(
        memory_v2_retrieve.memory_claim_store,
        "list_current_claims_matching_terms",
        list_lexical_claims,
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(
            memory_v2_bundle_ttl_seconds=3600,
            memory_retrieve_action_recall_enabled=False,
            memory_retrieve_lexical_recall_enabled=True,
            memory_retrieve_lexical_recall_limit=80,
            memory_retrieve_lexical_recall_boost=0.08,
        ),
    )
    body = _body("EXACT", 0.0).model_copy(
        update={"query": "How much did I spend on bike expenses?"}
    )

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert "expense" in {item.claim_id for item in result.items}
    assert {"bike", "expens"}.issubset(result.retrieval_trace["lexical_terms"])
    assert result.retrieval_trace["lexical_recalled"] == 1


@pytest.mark.asyncio
async def test_retrieve_recalls_and_preserves_each_compound_query_facet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = {
        "general": {**_claim(), "claim_id": "general", "text": "I enjoy model kits."},
        "worked": {
            **_claim(),
            "claim_id": "worked",
            "text": "I worked on a Gundam model kit.",
        },
        "bought": {
            **_claim(),
            "claim_id": "bought",
            "text": "I bought a vintage car model kit.",
        },
    }

    async def list_claims(*args, **kwargs):
        return []

    async def search_vectors(*args, **kwargs):
        query = args[4]
        if query == "model kits worked":
            return [{"claim_id": "worked", "score": 0.75}]
        if query == "model kits bought":
            return [{"claim_id": "bought", "score": 0.70}]
        return [{"claim_id": "general", "score": 0.95}]

    async def list_by_ids(*args, **kwargs):
        return [claims[claim_id] for claim_id in args[4]]

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(
        memory_v2_retrieve.memory_claim_store, "list_current_claims_by_ids", list_by_ids
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(memory_v2_retrieve.qdrant_store, "search_claim_vectors", search_vectors)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(
            memory_v2_bundle_ttl_seconds=3600,
            memory_retrieve_multifacet_enabled=True,
            memory_retrieve_multifacet_max_queries=4,
            memory_retrieve_multifacet_candidate_limit=30,
            memory_retrieve_multifacet_max_items=12,
            memory_retrieve_action_recall_enabled=False,
            memory_retrieve_lexical_recall_enabled=False,
            memory_retrieve_evidence_neighbor_enabled=False,
            memory_retrieve_session_diversity_enabled=False,
            memory_retrieve_vector_weight=0.75,
        ),
    )
    body = _body("SEMANTIC", 0.0).model_copy(
        update={
            "query": "How many model kits have I worked on or bought?",
            "top_k": 3,
        }
    )

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert [item.claim_id for item in result.items] == ["general", "worked", "bought"]
    assert result.retrieval_trace["query_facet_count"] == 3
    assert result.retrieval_trace["query_facet_hits"] == [1, 1, 1]


@pytest.mark.asyncio
async def test_retrieve_returns_only_safe_increments_with_audit_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = {**_claim(), "claim_id": "claim-duplicate", "text": "公司办公地点在上海市浦东新区"}
    conflict = {
        **_claim(),
        "claim_id": "claim-conflict",
        "dimension": "financing_target",
        "claim_key": "amount",
        "value": {"amount": 3000},
        "text": "历史融资目标为3000万元",
    }
    increment = {
        **_claim(),
        "claim_id": "claim-increment",
        "dimension": "team_profile",
        "claim_key": "founder",
        "value": "张三",
        "text": "创始人为张三",
    }
    saved = {}

    async def list_claims(*args, **kwargs):
        return [duplicate, conflict, increment]

    async def save_bundle(doc):
        saved.update(doc)

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(memory_v2_bundle_ttl_seconds=3600),
    )
    body = _body("EXACT", 0.0).model_copy(
        update={
            "query": "",
            "current_context": MemoryCurrentContext(
                meeting_id="meeting-2",
                raw_text="本场确认公司办公地点在上海市浦东新区。",
                claims=[
                    MemoryCurrentClaim(
                        dimension="financing_target",
                        claim_key="amount",
                        value={"amount": 4000},
                    )
                ],
            ),
        }
    )

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert [item.claim_id for item in result.items] == ["claim-increment"]
    assert result.dropped_current_duplicate_claim_ids == ["claim-duplicate"]
    assert result.conflicting_claim_ids == ["claim-conflict"]
    assert result.effective_injection_count == 1
    assert result.no_hit_reason is None
    assert saved["dropped_current_duplicate_claim_ids"] == ["claim-duplicate"]


@pytest.mark.asyncio
async def test_legacy_request_without_profile_or_context_keeps_previous_selection_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = {**_claim(), "claim_id": "claim-1"}
    second = {**_claim(), "claim_id": "claim-2"}

    async def list_claims(*args, **kwargs):
        return [first, second]

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(memory_v2_bundle_ttl_seconds=3600),
    )
    body = _body("EXACT", 0.0).model_copy(update={"query": ""})

    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), body
    )

    assert [item.claim_id for item in result.items] == ["claim-1", "claim-2"]
    assert result.dropped_redundant_claim_ids == []


@pytest.mark.asyncio
async def test_unrelated_query_returns_empty_instead_of_first_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def list_claims(*args, **kwargs):
        return [_claim()]

    async def no_vectors(*args, **kwargs):
        return []

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(memory_v2_retrieve.qdrant_store, "search_claim_vectors", no_vectors)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(memory_v2_bundle_ttl_seconds=3600),
    )
    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), _body()
    )
    assert result.items == []
    assert result.excluded["below_score"] == 1


@pytest.mark.asyncio
async def test_valid_empty_llm_selection_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def list_claims(*args, **kwargs):
        return [_claim()]

    async def no_vectors(*args, **kwargs):
        return []

    async def empty_rerank(*args, **kwargs):
        return {}

    async def save_bundle(doc):
        return doc

    monkeypatch.setattr(
        memory_v2_retrieve.memory_policy, "ensure_retrieve_permission", lambda *a: None
    )
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "save_bundle", save_bundle)
    monkeypatch.setattr(memory_v2_retrieve.qdrant_store, "search_claim_vectors", no_vectors)
    monkeypatch.setattr(memory_v2_retrieve, "_rerank_with_llm", empty_rerank)
    monkeypatch.setattr(
        memory_v2_retrieve,
        "get_settings",
        lambda: SimpleNamespace(memory_v2_bundle_ttl_seconds=3600),
    )
    result = await memory_v2_retrieve.retrieve(
        SimpleNamespace(), RequestContext(tenant_id=1, org_id=2), _body("LLM", 0.0)
    )
    assert result.items == []


@pytest.mark.asyncio
async def test_call_revalidates_allow_llm_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    claim = _claim()
    claim["access_policy"] = {**claim["access_policy"], "allow_llm": False}

    async def get_bundle(*args, **kwargs):
        return {
            "bundle_id": "bundle-1",
            "user_id": "user-1",
            "claim_ids": ["claim-1"],
            "items": [{"claim_id": "claim-1", "text": claim["text"]}],
            "usage_context": _body().usage_context.model_dump(),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }

    async def list_claims(*args, **kwargs):
        return [claim]

    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "get_bundle", get_bundle)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    ctx = RequestContext(tenant_id=1, org_id=2, permissions={"memory:retrieve:cross"})
    with pytest.raises(ForbiddenError):
        await memory_v2_retrieve.call(
            SimpleNamespace(),
            ctx,
            MemoryCallV2Request(
                bundle_id="bundle-1",
                module_id="meeting_summary",
                prompt_template="<memory_context>",
                use_llm=True,
            ),
        )


@pytest.mark.asyncio
async def test_call_accepts_mongodb_naive_utc_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_bundle(*args, **kwargs):
        return {
            "bundle_id": "bundle-1",
            "user_id": "user-1",
            "claim_ids": [],
            "items": [],
            "usage_context": _body().usage_context.model_dump(),
            # PyMongo returns UTC datetimes without tzinfo unless tz_aware is enabled.
            "expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
        }

    async def list_claims(*args, **kwargs):
        return []

    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "get_bundle", get_bundle)
    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "list_current_claims", list_claims)
    ctx = RequestContext(tenant_id=1, org_id=2, permissions={"memory:retrieve:cross"})

    result = await memory_v2_retrieve.call(
        SimpleNamespace(),
        ctx,
        MemoryCallV2Request(
            bundle_id="bundle-1",
            module_id="meeting_summary",
            prompt_template="before <memory_context> after",
            use_llm=False,
        ),
    )

    assert result.bundle_id == "bundle-1"
    assert result.result == "before [] after"


@pytest.mark.asyncio
async def test_call_rejects_expired_mongodb_naive_utc_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_bundle(*args, **kwargs):
        return {
            "bundle_id": "bundle-1",
            "expires_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1),
        }

    monkeypatch.setattr(memory_v2_retrieve.memory_claim_store, "get_bundle", get_bundle)
    ctx = RequestContext(tenant_id=1, org_id=2, permissions={"memory:retrieve:cross"})

    with pytest.raises(NotFoundError, match="expired"):
        await memory_v2_retrieve.call(
            SimpleNamespace(),
            ctx,
            MemoryCallV2Request(
                bundle_id="bundle-1",
                module_id="meeting_summary",
                prompt_template="<memory_context>",
                use_llm=False,
            ),
        )
