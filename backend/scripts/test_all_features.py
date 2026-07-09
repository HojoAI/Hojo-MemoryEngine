#!/usr/bin/env python3
"""Integration tests for Memory Engine v0.5 feature set.

Usage::

    export APP_DISABLE_AUTH=true
    export KAFKA_CONSUMERS_ENABLED=false
    # start API: uvicorn memory_engine.main:app --port 6030
    cd backend && .venv/bin/python scripts/test_all_features.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:6030").rstrip("/")
API = f"{BASE}/api/v1"
ADMIN_SECRET = os.getenv("ADMIN_BOOTSTRAP_SECRET", "change-me-local-dev")
DISABLE_AUTH = os.getenv("APP_DISABLE_AUTH", "true").lower() in ("1", "true", "yes")


def headers(*, api_key: str | None = None, tenant_id: int | None = None, org_id: int | None = None) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if DISABLE_AUTH:
        h["X-Tenant-Id"] = str(tenant_id or os.getenv("E2E_TENANT_ID", "1"))
        h["X-Org-Id"] = str(org_id or os.getenv("E2E_ORG_ID", "1"))
    elif api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def run_step(name: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    field = f"test_field_{uuid.uuid4().hex[:6]}"
    user_id = f"user_{uuid.uuid4().hex[:6]}"
    passed = 0
    failed = 0

    with httpx.Client(timeout=60) as client:
        # Health
        if run_step("GET /health", client.get(f"{BASE}/health").status_code == 200):
            passed += 1
        else:
            failed += 1

        # Admin bootstrap (optional)
        boot_headers = {"X-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"}
        code = f"t_{uuid.uuid4().hex[:6]}"
        boot = client.post(
            f"{API}/admin/tenants",
            headers=boot_headers,
            json={
                "tenant_code": code,
                "tenant_name": "Test Tenant",
                "org_code": "main",
                "org_name": "Main",
                "email": f"{code}@test.local",
            },
        )
        api_key: str | None = None
        tenant_id = int(os.getenv("E2E_TENANT_ID", "1"))
        org_id = int(os.getenv("E2E_ORG_ID", "1"))
        if boot.status_code == 200 and boot.json().get("code") == 0:
            d = boot.json()["data"]
            api_key = d["api_key"]
            tenant_id = d["tenant_id"]
            org_id = d["org_id"]
            if run_step("POST /admin/tenants", True, f"tenant_id={tenant_id}"):
                passed += 1
            else:
                failed += 1
        else:
            api_key = os.getenv("MOS_API_KEY", "mos_devtest00001ab")
            if run_step("POST /admin/tenants", True, f"skipped use MOS_API_KEY ({boot.status_code})"):
                passed += 1
            else:
                failed += 1

        h = headers(api_key=api_key, tenant_id=tenant_id, org_id=org_id)

        # Schema CRUD
        r = client.post(
            f"{API}/schema/create",
            headers=h,
            json={
                "name": field,
                "match_method": "MERGE",
                "storage_type": "KV",
                "source": "api",
            },
        )
        if run_step("POST /schema/create", r.status_code == 200):
            passed += 1
        else:
            failed += 1

        # Retrieve rule CRUD
        rr = client.post(
            f"{API}/schema/retrieve/create",
            headers=h,
            json={
                "rule_name": "default_llm",
                "memory_field_name": field,
                "retrieve_method": "EXACT",
                "rule_config_json": {"prompt": "read memory"},
            },
        )
        if run_step("POST /schema/retrieve/create", rr.status_code == 200):
            passed += 1
        else:
            failed += 1

        rg = client.get(
            f"{API}/schema/retrieve/get",
            headers=h,
            params={"rule_name": "default_llm", "memory_field_name": field},
        )
        if run_step("GET /schema/retrieve/get", rg.status_code == 200):
            passed += 1
        else:
            failed += 1

        # Data create with write_rule
        dc = client.post(
            f"{API}/data/create",
            headers=h,
            json={
                "user_id": user_id,
                "memory_field_name": field,
                "value": {"a": 1},
                "write_rule": "OVERWRITE",
            },
        )
        if run_step("POST /data/create + write_rule", dc.status_code == 200):
            passed += 1
        else:
            failed += 1

        client.post(
            f"{API}/data/create",
            headers=h,
            json={
                "user_id": user_id,
                "memory_field_name": field,
                "value": {"b": 2},
                "write_rule": "MERGE",
            },
        )

        # Data list
        dl = client.get(f"{API}/data/list", headers=h, params={"user_id": user_id})
        list_payload = dl.json().get("data") or {}
        list_items = (
            list_payload.get("items", list_payload)
            if isinstance(list_payload, dict)
            else list_payload
        )
        if run_step("GET /data/list", dl.status_code == 200 and len(list_items) >= 1):
            passed += 1
        else:
            failed += 1

        # Retrieve with rule_name
        dr = client.post(
            f"{API}/data/retrieve",
            headers=h,
            json={
                "user_id": user_id,
                "memory_field_name": field,
                "rule_name": "default_llm",
                "rule": {"method": "EXACT"},
            },
        )
        if run_step("POST /data/retrieve + rule_name", dr.status_code == 200):
            passed += 1
        else:
            failed += 1

        # Billing emit
        be = client.post(
            f"{API}/billing/events/emit",
            headers=h,
            params={"event_type": "llm_completion", "total_tokens": 100},
        )
        if run_step("POST /billing/events/emit", be.status_code == 200):
            passed += 1
        else:
            failed += 1

        bl = client.get(f"{API}/billing/events", headers=h, params={"limit": 5})
        if run_step("GET /billing/events", bl.status_code == 200):
            passed += 1
        else:
            failed += 1

        # Cleanup schema
        client.post(f"{API}/schema/delete", headers=h, params={"name": field})

    print("-" * 50)
    print(f"Summary: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
