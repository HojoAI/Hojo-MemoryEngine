"""Tests for Canal adapter, capability registry, schema sync gating."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.integrations import canal_adapter
from memory_engine.integrations import schema_sync
from memory_engine.schemas.capability import CapabilityRegisterBody
from memory_engine.schemas.rules import ParseRuleCreate


def test_canal_parse_memory_field_update() -> None:
    raw = json.dumps(
        {
            "database": "memory_engine",
            "table": "memory_field",
            "type": "UPDATE",
            "ts": 1710000000000,
            "isDdl": False,
            "data": [
                {
                    "id": "10",
                    "tenant_id": "1",
                    "org_id": "0",
                    "name": "年龄",
                    "deleted": "0",
                    "version": "2",
                    "value_type": "number",
                    "match_method": "OVERWRITE",
                    "storage_type": "KV",
                    "status": "active",
                }
            ],
        }
    ).encode()
    events = canal_adapter.parse_canal_message(raw)
    assert len(events) == 1
    assert events[0]["table"] == "memory_field"
    assert events[0]["memory_field_name"] == "年龄"
    assert events[0]["source"] == "canal"


def test_canal_parse_capability_insert() -> None:
    raw = json.dumps(
        {
            "database": "memory_engine",
            "table": "capability_registry",
            "type": "INSERT",
            "ts": 1,
            "data": [
                {
                    "id": "5",
                    "tenant_id": "1",
                    "org_id": "0",
                    "capability_name": "parse_age",
                    "module_name": "myapp.parsers",
                    "service_name": "parse_age",
                    "rule_kind": "parse",
                    "deleted": "0",
                    "version": "1",
                    "enabled": "1",
                }
            ],
        }
    ).encode()
    events = canal_adapter.parse_canal_message(raw)
    assert events[0]["table"] == "capability_registry"
    assert events[0]["payload"]["capability_name"] == "parse_age"


@pytest.mark.asyncio
async def test_schema_sync_skips_when_canal_primary() -> None:
    with patch("memory_engine.integrations.schema_sync.get_settings") as gs:
        gs.return_value.canal_enabled = True
        gs.return_value.schema_sync_api_publish = False
        gs.return_value.canal_mysql_database = "memory_engine"
        with patch(
            "memory_engine.integrations.schema_sync.publish_changelog_event", new_callable=AsyncMock
        ) as mock_pub:
            await schema_sync.publish_memory_field_change(
                tenant_id=1,
                org_id=0,
                memory_field_name="x",
                event_type="create",
            )
            mock_pub.assert_not_awaited()


@pytest.mark.asyncio
async def test_capability_register_body() -> None:
    body = CapabilityRegisterBody(
        capability_name="c1",
        module_name="app.mod",
        service_name="run",
        rule_kind="parse",
    )
    assert body.rule_kind == "parse"


@pytest.mark.asyncio
async def test_resolve_capability_id_registers() -> None:
    ctx = RequestContext(tenant_id=1, org_id=0, user_id=1)
    session = AsyncMock()
    from memory_engine.schemas.capability import CapabilityOut

    fake_out = CapabilityOut(
        id=99,
        tenant_id=1,
        org_id=0,
        capability_name="cap",
        module_name="m",
        service_name="s",
        rule_kind="parse",
    )

    with patch(
        "memory_engine.services.capability_registry.register",
        new_callable=AsyncMock,
        return_value=fake_out,
    ) as mock_reg:
        from memory_engine.services import capability_registry as cap_svc

        cap_id = await cap_svc.resolve_capability_id(
            session,
            ctx,
            capability_name="cap",
            module_name="m",
            service_name="s",
            rule_kind="parse",
        )
    assert cap_id == 99
    mock_reg.assert_awaited_once()


def test_parse_rule_create_has_capability_fields() -> None:
    body = ParseRuleCreate(
        memory_field_name="f",
        rule_name="r",
        capability_name="cap",
        module_name="mod",
        service_name="svc",
    )
    assert body.module_name == "mod"
