"""Permission wildcard tests."""

from memory_engine.core.permissions import permission_granted


def test_exact_permission() -> None:
    assert permission_granted({"schema:read"}, "schema:read")


def test_wildcard_prefix() -> None:
    assert permission_granted({"schema:*"}, "schema:create")
    assert permission_granted({"governance:*"}, "governance:write")


def test_denied() -> None:
    assert not permission_granted({"billing:read"}, "schema:read")
