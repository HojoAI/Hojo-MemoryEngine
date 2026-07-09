"""Shared HTTP base URL and auth headers."""

import os


def base_url() -> str:
    return os.environ.get("MEMORY_ENGINE_API_BASE", "http://127.0.0.1:6030/api/v1")


def headers() -> dict[str, str]:
    h: dict[str, str] = {
        "X-Tenant-Id": os.environ.get("MEMORY_ENGINE_TENANT_ID", "1"),
        "X-Org-Id": os.environ.get("MEMORY_ENGINE_ORG_ID", "0"),
    }
    if uid := os.environ.get("MEMORY_ENGINE_USER_ID"):
        h["X-User-Id"] = uid
    prefix = os.environ.get("MEMORY_ENGINE_API_KEY_PREFIX", "").strip()
    if not prefix and (key := os.environ.get("MEMORY_ENGINE_API_KEY", "").strip()):
        prefix = key[:16] if len(key) >= 16 else key[:8]
    if prefix:
        h["X-Api-Key-Prefix"] = prefix
    if key := os.environ.get("MEMORY_ENGINE_API_KEY"):
        h["Authorization"] = f"Bearer {key}"
    return h
