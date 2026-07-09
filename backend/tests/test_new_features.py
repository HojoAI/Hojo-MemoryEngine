"""Tests for admin, rules resolution, billing, schema sync."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.schemas.memory_field import DataRetrieveRequest, RetrieveRuleBody
from memory_engine.schemas.rules import RetrieveRuleCreate
from memory_engine.services import memory_retrieve as retrieve_svc
from memory_engine.services import rules as rule_svc


@pytest.mark.asyncio
async def test_resolve_retrieve_rule_from_db() -> None:
    ctx = RequestContext(tenant_id=1, org_id=1)
    body = DataRetrieveRequest(
        user_id="u1",
        memory_field_name="年龄",
        rule_name="r1",
        rule=RetrieveRuleBody(method="EXACT"),
    )
    fake_rule = MagicMock()
    fake_rule.retrieve_method = "REGEX"
    fake_rule.memory_field_name = "年龄"
    fake_rule.rule_config_json = {"prompt": "pat"}

    with patch.object(
        rule_svc, "get_active_retrieve", new_callable=AsyncMock, return_value=fake_rule
    ), patch.object(
        rule_svc, "retrieve_rule_to_body", return_value={"method": "REGEX", "prompt": "pat", "llm": None}
    ):
        merged = await retrieve_svc._resolve_retrieve_rule(None, ctx, body)  # type: ignore[arg-type]
    assert merged.rule.method == "REGEX"
    assert merged.rule.prompt == "pat"


@pytest.mark.asyncio
async def test_publish_schema_changelog() -> None:
    with patch(
        "memory_engine.integrations.schema_sync.publish_changelog_event", new_callable=AsyncMock
    ) as mock_pub:
        from memory_engine.integrations import schema_sync

        await schema_sync.publish_memory_field_change(
            tenant_id=1,
            org_id=1,
            memory_field_name="f",
            event_type="update",
        )
        mock_pub.assert_awaited_once()


@pytest.mark.asyncio
async def test_billing_emit_llm() -> None:
    ctx = RequestContext(tenant_id=1, org_id=1, user_id=1)
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch("memory_engine.services.billing_service.publish", new_callable=AsyncMock):
        from memory_engine.services import billing_service

        uid = await billing_service.emit_llm_completion(
            session, ctx, model_name="gpt-test", prompt_tokens=10, completion_tokens=5
        )
    assert len(uid) == 36
    session.commit.assert_awaited()
