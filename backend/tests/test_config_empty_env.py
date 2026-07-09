"""Settings tolerate empty-string env vars from K8s/CI placeholders."""

import pytest

from memory_engine.config import Settings, get_settings


def test_empty_float_and_bool_env_use_defaults() -> None:
    s = Settings(
        openai_request_timeout_seconds="",
        kafka_publish_enabled="",
    )
    assert s.openai_request_timeout_seconds == 60.0
    assert s.kafka_publish_enabled is True


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
