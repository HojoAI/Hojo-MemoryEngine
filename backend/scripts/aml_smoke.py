#!/usr/bin/env python3
"""Run an AML-compatible Add/Search/isolation/idempotency smoke test."""

from __future__ import annotations

import argparse
import os
import sys
from uuid import uuid4

import httpx


def _headers(api_key: str, auth_mode: str) -> dict[str, str]:
    if not api_key:
        return {}
    if auth_mode == "x-api-key":
        return {"X-Api-Key": api_key}
    return {"Authorization": f"{auth_mode.title()} {api_key}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("AML_BASE_URL", "http://127.0.0.1:6030"))
    parser.add_argument("--api-key", default=os.getenv("AML_MEMORY_SYSTEM_KEY", ""))
    parser.add_argument(
        "--auth-mode",
        choices=("bearer", "token", "x-api-key"),
        default=os.getenv("AML_AUTH_MODE", "bearer"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    run_id = uuid4().hex
    user_id = f"aml-smoke:{run_id}:user"
    other_user_id = f"aml-smoke:{run_id}:other"
    request = {
        "request_id": f"aml-smoke:{run_id}:chunk-0",
        "messages": [
            {
                "role": "user",
                "timestamp": 1767225600000,
                "content": "My dog's name is Poppy and her favorite toy is a green rope.",
            }
        ],
        "user_id": user_id,
        "session_id": f"aml-smoke:{run_id}:session-0",
    }
    headers = _headers(args.api_key, args.auth_mode)
    with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout) as client:
        health = client.get("/aml/health")
        health.raise_for_status()

        first_add = client.post("/aml/add", json=request)
        first_add.raise_for_status()
        if first_add.json().get("success") is not True:
            raise RuntimeError(f"unexpected Add response: {first_add.text}")

        repeated_add = client.post("/aml/add", json=request)
        repeated_add.raise_for_status()
        if repeated_add.json() != first_add.json():
            raise RuntimeError("idempotent Add response changed")

        search = client.post(
            "/aml/search",
            json={"query": "What is my dog's name?", "user_id": user_id, "top_k": 100},
        )
        search.raise_for_status()
        data = search.json().get("data") or []
        if not data or "Poppy" not in data[0].get("content", ""):
            raise RuntimeError(f"expected evidence was not retrieved: {search.text}")

        isolated = client.post(
            "/aml/search",
            json={"query": "What is my dog's name?", "user_id": other_user_id, "top_k": 100},
        )
        isolated.raise_for_status()
        if isolated.json().get("data"):
            raise RuntimeError("cross-user memory leak detected")

        cleanup = client.post("/aml/clear", json={"user_id": user_id})
        cleanup.raise_for_status()

    print("AML smoke passed: health, synchronous Add, idempotency, Search, isolation, cleanup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
