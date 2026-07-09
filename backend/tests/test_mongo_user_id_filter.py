"""Tests for Mongo tenant list user_id substring filter."""

from memory_engine.integrations.mongo_store import _memory_data_tenant_query, _user_id_substring_filter


def test_user_id_substring_filter_empty() -> None:
    assert _user_id_substring_filter(None) == {}
    assert _user_id_substring_filter("") == {}
    assert _user_id_substring_filter("   ") == {}


def test_user_id_substring_filter_partial_match() -> None:
    assert _user_id_substring_filter("137384") == {
        "user_id": {"$regex": "137384"},
    }


def test_user_id_substring_filter_escapes_regex() -> None:
    assert _user_id_substring_filter("137.384") == {
        "user_id": {"$regex": "137\\.384"},
    }


def test_memory_data_tenant_query_includes_substring_filter() -> None:
    query = _memory_data_tenant_query(2, 2, user_id="865218")
    assert query["tenant_id"] == 2
    assert query["org_id"] == 2
    assert query["deleted"] == 0
    assert query["user_id"] == {"$regex": "865218"}
