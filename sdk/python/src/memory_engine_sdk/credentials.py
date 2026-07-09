"""API key prefix + secret validation for SDK calls."""

from __future__ import annotations

import os
from typing import Any, TypedDict

import httpx

from memory_engine_sdk.transport import base_url, headers


class MemoryEngineConfigError(RuntimeError):
    """Missing or invalid ``MEMORY_ENGINE_*`` environment configuration."""


class SessionInfo(TypedDict):
    key_prefix: str
    app_user_id: int
    memory_user_id: str
    tenant_id: int
    org_id: int
    valid: bool


_session_cache: SessionInfo | None = None


def derive_prefix_from_secret(raw_key: str) -> str:
    """Match server lookup: first 16 chars of the full API key (or 8 if shorter)."""
    key = raw_key.strip()
    return key[:16] if len(key) >= 16 else key[:8]


def require_api_key_prefix() -> str:
    """Return explicit ``MEMORY_ENGINE_API_KEY_PREFIX`` if set."""
    prefix = os.environ.get("MEMORY_ENGINE_API_KEY_PREFIX", "").strip()
    if not prefix:
        raise MemoryEngineConfigError(
            "未设置 MEMORY_ENGINE_API_KEY_PREFIX，且无法从 MEMORY_ENGINE_API_KEY 推导。"
        )
    return prefix


def resolve_key_prefix() -> str:
    """Prefix from env, or derived from full ``MEMORY_ENGINE_API_KEY`` (same rule as API server)."""
    explicit = os.environ.get("MEMORY_ENGINE_API_KEY_PREFIX", "").strip()
    if explicit:
        return explicit
    return derive_prefix_from_secret(require_api_key_secret())


def require_api_key_secret() -> str:
    """Return full Bearer secret (``MEMORY_ENGINE_API_KEY``)."""
    key = os.environ.get("MEMORY_ENGINE_API_KEY", "").strip()
    if not key:
        raise MemoryEngineConfigError(
            "未设置 MEMORY_ENGINE_API_KEY。"
            "请使用申请 Key 时一次性展示的完整密钥（非仅前缀）。"
        )
    return key


def _api_response_detail(response: httpx.Response) -> str:
    """Extract FastAPI ``detail`` (or body snippet) from an error response."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:300]
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return str(detail)
    msg = payload.get("message")
    return str(msg) if msg else ""


def _raise_session_http_error(response: httpx.Response) -> None:
    """Map ``GET /onboarding/session`` failures to ``MemoryEngineConfigError``."""
    detail = _api_response_detail(response)
    api_base = os.environ.get("MEMORY_ENGINE_API_BASE", "").strip() or "(未设置 MEMORY_ENGINE_API_BASE)"
    status = response.status_code

    if status in (401, 403):
        if any(
            token in detail
            for token in (
                "Missing Bearer",
                "Bearer API key required",
            )
        ):
            raise MemoryEngineConfigError(
                "未提供有效的 MEMORY_ENGINE_API_KEY（Bearer）。\n"
                "请 export MEMORY_ENGINE_API_KEY=申请时一次性展示的完整密钥（以 mos_ 开头）。"
            )
        if "Invalid API key" in detail or "API key not found" in detail:
            raise MemoryEngineConfigError(
                "MEMORY_ENGINE_API_KEY 无效或错误：服务端拒绝了当前密钥。\n"
                "请确认使用的是完整密钥（非仅前缀、非占位符、非他人 Key）。\n"
                f"当前 API: {api_base}\n"
                f"服务端说明: {detail or 'Invalid API key'}"
            )
        if "API key revoked" in detail:
            raise MemoryEngineConfigError(
                "MEMORY_ENGINE_API_KEY 已吊销。请在 Dashboard 重新申请 Key 并更新环境变量。"
            )
        if "API key expired" in detail:
            raise MemoryEngineConfigError(
                "MEMORY_ENGINE_API_KEY 已过期。请在 Dashboard 重新申请 Key 并更新环境变量。"
            )
        if "X-Tenant-Id does not match" in detail:
            raise MemoryEngineConfigError(
                "MEMORY_ENGINE_TENANT_ID 与当前 API Key 所属租户不一致。\n"
                f"服务端说明: {detail}"
            )
        if "X-Org-Id does not match" in detail:
            raise MemoryEngineConfigError(
                "MEMORY_ENGINE_ORG_ID 与当前 API Key 所属组织不一致。\n"
                f"服务端说明: {detail}"
            )

    raise MemoryEngineConfigError(
        f"无法验证 API Key（HTTP {status}）。\n"
        "请检查 MEMORY_ENGINE_API_KEY、MEMORY_ENGINE_API_BASE、MEMORY_ENGINE_TENANT_ID、MEMORY_ENGINE_ORG_ID。\n"
        f"API: {api_base}\n"
        f"服务端说明: {detail or response.reason_phrase}"
    )


def _fetch_session() -> SessionInfo:
    """Load and cache authenticated session from ``GET /onboarding/session``."""
    global _session_cache
    if _session_cache is not None:
        return _session_cache

    require_api_key_secret()
    r = httpx.get(
        f"{base_url()}/onboarding/session",
        headers=headers(),
        timeout=30,
    )
    if r.status_code >= 400:
        _raise_session_http_error(r)
    data = r.json().get("data") or {}
    _session_cache = SessionInfo(
        key_prefix=str(data["key_prefix"]),
        app_user_id=int(data["app_user_id"]),
        memory_user_id=str(data.get("memory_user_id") or data["key_prefix"]),
        tenant_id=int(data["tenant_id"]),
        org_id=int(data["org_id"]),
        valid=bool(data.get("valid", True)),
    )
    return _session_cache


def clear_session_cache() -> None:
    """Reset cached session (tests)."""
    global _session_cache
    _session_cache = None


def validate_prefix_for_read() -> str:
    """Validate API key via ``/onboarding/session``; return authoritative ``key_prefix``."""
    require_api_key_secret()
    session = _fetch_session()
    if not session["valid"]:
        raise MemoryEngineConfigError(
            f"API Key 无效或已吊销（前缀 {session['key_prefix']!r}）。"
            "请在 Dashboard 重新申请 Key。"
        )
    expected = resolve_key_prefix()
    if session["key_prefix"] != expected:
        raise MemoryEngineConfigError(
            f"MEMORY_ENGINE_API_KEY 与 MEMORY_ENGINE_API_KEY_PREFIX 不一致："
            f"env 前缀={expected!r}，服务端={session['key_prefix']!r}。"
            "可删除 MEMORY_ENGINE_API_KEY_PREFIX，仅保留完整 MEMORY_ENGINE_API_KEY。"
        )
    return session["key_prefix"]


def ensure_write_context() -> str:
    """Validate prefix + secret before mutating API calls (POST/PUT)."""
    return validate_prefix_for_read()


def memory_user_id() -> str:
    """Mongo ``user_id`` partition: server ``memory_user_id`` (= ``key_prefix`` for this key)."""
    ensure_write_context()
    return _fetch_session()["memory_user_id"]
