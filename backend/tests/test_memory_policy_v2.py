"""P0 namespace, scope, module and sensitivity policy tests."""

from types import SimpleNamespace

import pytest

from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.schemas.memory_claim import MemoryNamespace, MemoryUsageContext
from memory_engine.services import memory_policy


def _usage(scope: str = "cross") -> MemoryUsageContext:
    return MemoryUsageContext(
        module_id="meeting_summary",
        scenario="financing",
        scope=scope,
        current_meeting_id="m-current",
        namespace=MemoryNamespace(type="financing_project", id="deal-1"),
        caller_role="investor",
    )


def _claim(**overrides):
    claim = {
        "claim_id": "c1",
        "namespace": {"type": "financing_project", "id": "deal-1"},
        "lifecycle_status": "active",
        "is_current": True,
        "access_policy": {
            "allowed_modules": ["meeting_summary"],
            "allowed_scenarios": ["financing"],
            "allowed_scopes": ["self", "cross"],
            "allowed_roles": ["investor"],
            "sensitivity": "internal",
            "allow_llm": True,
        },
        "provenance": [{"meeting_id": "m-history"}],
    }
    claim.update(overrides)
    return claim


def test_cross_scope_and_namespace_are_hard_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_policy, "get_settings", lambda: SimpleNamespace(app_disable_auth=False))
    ctx = RequestContext(tenant_id=1, permissions={"memory:retrieve:cross"})
    foreign = _claim(namespace={"type": "financing_project", "id": "deal-2"})
    same_meeting = _claim(provenance=[{"meeting_id": "m-current"}])
    allowed, excluded = memory_policy.filter_claims(
        ctx, [_claim(), foreign, same_meeting], _usage(), llm_requested=False
    )
    assert [item["claim_id"] for item in allowed] == ["c1"]
    assert excluded["different_namespace"] == 1
    assert excluded["scope_mismatch"] == 1


def test_sensitive_claim_requires_extra_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_policy, "get_settings", lambda: SimpleNamespace(app_disable_auth=False))
    ctx = RequestContext(tenant_id=1, permissions={"memory:retrieve:cross"})
    sensitive = _claim()
    sensitive["access_policy"] = {**sensitive["access_policy"], "sensitivity": "sensitive"}
    allowed, excluded = memory_policy.filter_claims(
        ctx, [sensitive], _usage(), llm_requested=True
    )
    assert allowed == []
    assert excluded["permission_denied"] == 1


def test_cross_retrieve_requires_explicit_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_policy, "get_settings", lambda: SimpleNamespace(app_disable_auth=False))
    with pytest.raises(ForbiddenError):
        memory_policy.ensure_retrieve_permission(RequestContext(tenant_id=1), _usage())
