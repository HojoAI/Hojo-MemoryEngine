"""MongoDB DSN construction from settings."""

import pytest

from memory_engine.config import Settings, get_settings


def test_mongodb_dsn_without_auth() -> None:
    s = Settings(mongodb_uri="mongodb://10.0.0.1", mongodb_port=27018)
    assert s.mongodb_dsn == "mongodb://10.0.0.1:27018"


def test_mongodb_dsn_with_user_password() -> None:
    s = Settings(
        mongodb_uri="mongodb://mongo.internal",
        mongodb_port=27017,
        mongodb_user="memos",
        mongodb_password="p@ss",
        mongodb_auth_source="admin",
    )
    assert s.mongodb_dsn == "mongodb://memos:p%40ss@mongo.internal:27017?authSource=admin"


def test_mongodb_dsn_credentials_override_uri_embedded() -> None:
    s = Settings(
        mongodb_uri="mongodb://old:old@127.0.0.1",
        mongodb_port=27017,
        mongodb_user="new",
        mongodb_password="secret",
    )
    assert s.mongodb_dsn == "mongodb://new:secret@127.0.0.1:27017?authSource=admin"


def test_mongodb_dsn_default_auth_source_when_user_set() -> None:
    s = Settings(
        mongodb_uri="mongodb://127.0.0.1",
        mongodb_port=27017,
        mongodb_user="u",
        mongodb_password="p",
    )
    assert "authSource=admin" in s.mongodb_dsn


def test_mongodb_dsn_custom_port() -> None:
    s = Settings(mongodb_uri="mongodb://mongo.internal", mongodb_port=37017)
    assert s.mongodb_dsn == "mongodb://mongo.internal:37017"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
