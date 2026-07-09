"""Tests for API key prefix credentials (no HTTP)."""

import os
from unittest.mock import MagicMock

import httpx
import pytest

from memory_engine_sdk.credentials import (
    MemoryEngineConfigError,
    _raise_session_http_error,
    clear_session_cache,
    derive_prefix_from_secret,
    require_api_key_prefix,
    require_api_key_secret,
    resolve_key_prefix,
    validate_prefix_for_read,
)


def test_require_api_key_prefix_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ENGINE_API_KEY_PREFIX", raising=False)
    with pytest.raises(MemoryEngineConfigError, match="MEMORY_ENGINE_API_KEY_PREFIX"):
        require_api_key_prefix()


def test_require_api_key_prefix_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ENGINE_API_KEY_PREFIX", "mos_Ufzwx1kKITli")
    assert require_api_key_prefix() == "mos_Ufzwx1kKITli"


def test_derive_prefix_from_secret() -> None:
    key = "mos_Ufzwx1kKITli" + "extra_secret_part"
    assert derive_prefix_from_secret(key) == "mos_Ufzwx1kKITli"


def test_resolve_key_prefix_from_secret_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ENGINE_API_KEY_PREFIX", raising=False)
    monkeypatch.setenv("MEMORY_ENGINE_API_KEY", "mos_Ufzwx1kKITliabcdefghij")
    assert resolve_key_prefix() == "mos_Ufzwx1kKITli"


def test_require_api_key_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ENGINE_API_KEY", raising=False)
    with pytest.raises(MemoryEngineConfigError, match="MEMORY_ENGINE_API_KEY"):
        require_api_key_secret()


def test_raise_session_http_error_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ENGINE_API_BASE", "http://api.memory-engine.example.com/api/v1")
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 403
    resp.reason_phrase = "Forbidden"
    resp.json.return_value = {"detail": "Invalid API key"}
    resp.text = '{"detail":"Invalid API key"}'
    with pytest.raises(MemoryEngineConfigError, match="MEMORY_ENGINE_API_KEY 无效"):
        _raise_session_http_error(resp)


def test_validate_prefix_maps_403_to_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_ENGINE_API_KEY", "mos_wrong_secret_key12")
    monkeypatch.setenv("MEMORY_ENGINE_API_BASE", "http://test/api/v1")

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 403
    resp.reason_phrase = "Forbidden"
    resp.json.return_value = {"detail": "Invalid API key"}
    resp.text = '{"detail":"Invalid API key"}'

    def _fake_get(*_args: object, **_kwargs: object) -> httpx.Response:
        return resp

    monkeypatch.setattr(httpx, "get", _fake_get)
    clear_session_cache()
    with pytest.raises(MemoryEngineConfigError, match="MEMORY_ENGINE_API_KEY"):
        validate_prefix_for_read()


def teardown_module() -> None:
    clear_session_cache()
