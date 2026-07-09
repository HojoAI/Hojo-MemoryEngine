"""Redis DSN construction from settings."""

import pytest

from memory_engine.config import Settings, get_settings


def test_redis_dsn_without_password() -> None:
    s = Settings(redis_url="redis://10.0.0.1", redis_port=6380, redis_database=2)
    assert s.redis_dsn == "redis://10.0.0.1:6380/2"


def test_redis_dsn_with_password() -> None:
    s = Settings(
        redis_url="redis://127.0.0.1",
        redis_port=6379,
        redis_password="s3cret!",
        redis_database=1,
    )
    assert s.redis_dsn == "redis://:s3cret%21@127.0.0.1:6379/1"


def test_redis_dsn_password_overrides_url_embedded() -> None:
    s = Settings(
        redis_url="redis://:old@127.0.0.1/5",
        redis_port=6379,
        redis_password="new",
        redis_database=0,
    )
    assert s.redis_dsn == "redis://:new@127.0.0.1:6379/0"


def test_redis_dsn_custom_port() -> None:
    s = Settings(redis_url="redis://redis.internal", redis_port=16379, redis_database=0)
    assert s.redis_dsn == "redis://redis.internal:16379/0"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
