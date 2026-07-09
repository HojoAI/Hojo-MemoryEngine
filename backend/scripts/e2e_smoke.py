#!/usr/bin/env python3
"""MemoryEngine end-to-end smoke / integration script.

Checks health, API key auth, schema CRUD, Temporal upsert, and Dreaming runs.

Usage (from repo root or backend/)::

    export MOS_API_KEY=mos_devtest00001ab
    python3 backend/scripts/e2e_smoke.py

    # or
    cd backend && poetry run python scripts/e2e_smoke.py

Environment (also read from repo ``.env``):

    API_BASE_URL          default http://127.0.0.1:6030
    MOS_API_KEY           Bearer token (required unless APP_DISABLE_AUTH=true)
    APP_DISABLE_AUTH      if true, sends X-Tenant-Id / X-Org-Id instead of Bearer
    E2E_TENANT_ID         default 1
    E2E_ORG_ID            default 1
    DREAMING_JOB_ID       default 1
    E2E_SKIP_TEMPORAL     1 to skip schema upsert workflow
    E2E_SKIP_DREAMING     1 to skip dreaming workflow
    E2E_WAIT_TIMEOUT_SEC  default 120
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ (setdefault)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


for candidate in (REPO_ROOT / ".env", BACKEND_ROOT / ".env"):
    load_dotenv(candidate)


@dataclass
class Settings:
    """Runtime settings for the smoke test."""

    base_url: str = field(default_factory=lambda: os.getenv("API_BASE_URL", "http://127.0.0.1:6030").rstrip("/"))
    api_key: str = field(default_factory=lambda: os.getenv("MOS_API_KEY", "mos_devtest00001ab"))
    disable_auth: bool = field(
        default_factory=lambda: os.getenv("APP_DISABLE_AUTH", "false").lower() in ("1", "true", "yes")
    )
    tenant_id: int = field(default_factory=lambda: int(os.getenv("E2E_TENANT_ID", "1")))
    org_id: int = field(default_factory=lambda: int(os.getenv("E2E_ORG_ID", "1")))
    dreaming_job_id: int = field(default_factory=lambda: int(os.getenv("DREAMING_JOB_ID", "1")))
    skip_temporal: bool = field(
        default_factory=lambda: os.getenv("E2E_SKIP_TEMPORAL", "").lower() in ("1", "true", "yes")
    )
    skip_dreaming: bool = field(
        default_factory=lambda: os.getenv("E2E_SKIP_DREAMING", "").lower() in ("1", "true", "yes")
    )
    wait_timeout_sec: float = field(default_factory=lambda: float(os.getenv("E2E_WAIT_TIMEOUT_SEC", "120")))
    http_timeout_sec: float = field(default_factory=lambda: float(os.getenv("E2E_HTTP_TIMEOUT_SEC", "30")))


@dataclass
class StepResult:
    """One check outcome."""

    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


class E2ERunner:
    """Runs ordered API checks."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.results: list[StepResult] = []
        self.field_name = f"e2e_field_{uuid.uuid4().hex[:8]}"
        self.dreaming_run_uuid: str | None = None

    def auth_headers(self, *, with_bearer: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.settings.disable_auth:
            headers["X-Tenant-Id"] = str(self.settings.tenant_id)
            headers["X-Org-Id"] = str(self.settings.org_id)
        elif with_bearer:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        return headers

    def record(self, name: str, ok: bool, detail: str = "", *, skipped: bool = False) -> None:
        self.results.append(StepResult(name=name, ok=ok, detail=detail, skipped=skipped))
        tag = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))

    def run(self) -> int:
        """Execute all steps; return process exit code."""
        print(f"API_BASE_URL={self.settings.base_url}")
        print(f"field_name={self.field_name}")
        print(f"auth={'disabled (headers)' if self.settings.disable_auth else 'api_key'}")
        print("-" * 60)

        timeout = httpx.Timeout(self.settings.http_timeout_sec)
        with httpx.Client(base_url=self.settings.base_url, timeout=timeout) as client:
            self._check_health(client)
            self._check_auth_rejected(client)
            self._check_schema_list(client)
            self._check_schema_create(client)
            self._check_schema_get(client)
            if not self.settings.skip_temporal:
                self._check_schema_upsert_temporal(client)
            else:
                self.record("schema/upsert (temporal)", True, "E2E_SKIP_TEMPORAL=1", skipped=True)
            if not self.settings.skip_dreaming:
                self._check_dreaming_run(client)
            else:
                self.record("dreaming/run", True, "E2E_SKIP_DREAMING=1", skipped=True)
            self._check_billing_events(client)

        return self._exit_code()

    def _check_health(self, client: httpx.Client) -> None:
        try:
            resp = client.get("/health")
            body = resp.json()
            ok = resp.status_code == 200 and body.get("status") == "ok"
            self.record("GET /health", ok, f"status={resp.status_code} body={body}")
        except httpx.HTTPError as exc:
            self.record("GET /health", False, str(exc))

    def _check_auth_rejected(self, client: httpx.Client) -> None:
        if self.settings.disable_auth:
            self.record("auth/reject without credentials", True, "skipped (APP_DISABLE_AUTH)", skipped=True)
            return
        try:
            resp = client.get("/api/v1/schema/list")
            ok = resp.status_code == 403
            self.record("GET /schema/list (no auth)", ok, f"status={resp.status_code}")
        except httpx.HTTPError as exc:
            self.record("GET /schema/list (no auth)", False, str(exc))

    def _check_schema_list(self, client: httpx.Client) -> None:
        try:
            resp = client.get("/api/v1/schema/list", headers=self.auth_headers())
            body = _safe_json(resp)
            ok = resp.status_code == 200 and body.get("code", 0) == 0
            count = len(body.get("data") or []) if isinstance(body.get("data"), list) else "?"
            self.record("GET /schema/list (auth)", ok, f"status={resp.status_code} items={count}")
        except httpx.HTTPError as exc:
            self.record("GET /schema/list (auth)", False, str(exc))

    def _check_schema_create(self, client: httpx.Client) -> None:
        payload = {
            "name": self.field_name,
            "description": "e2e smoke test",
            "value_type": "string",
            "match_method": "OVERWRITE",
            "storage_type": "KV",
            "source": "api",
        }
        try:
            resp = client.post(
                "/api/v1/schema/create",
                headers={**self.auth_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            body = _safe_json(resp)
            ok = resp.status_code == 200 and body.get("code", 0) == 0
            self.record("POST /schema/create", ok, f"status={resp.status_code} name={self.field_name}")
        except httpx.HTTPError as exc:
            self.record("POST /schema/create", False, str(exc))

    def _check_schema_get(self, client: httpx.Client) -> None:
        try:
            resp = client.get(
                "/api/v1/schema/get",
                params={"name": self.field_name},
                headers=self.auth_headers(),
            )
            body = _safe_json(resp)
            data = body.get("data") or {}
            ok = resp.status_code == 200 and body.get("code", 0) == 0 and data.get("name") == self.field_name
            detail = f"status={resp.status_code}" if ok else f"status={resp.status_code} data={data!r}"
            self.record("GET /schema/get", ok, detail)
        except httpx.HTTPError as exc:
            self.record("GET /schema/get", False, str(exc))

    def _check_schema_upsert_temporal(self, client: httpx.Client) -> None:
        upsert_name = f"{self.field_name}_upsert"
        payload = {
            "name": upsert_name,
            "description": "e2e temporal upsert",
            "value_type": "string",
            "match_method": "OVERWRITE",
            "storage_type": "KV",
            "source": "api",
        }
        wait_timeout = self.settings.wait_timeout_sec + 10
        try:
            started = time.monotonic()
            resp = client.post(
                "/api/v1/schema/upsert",
                params={"wait": "true"},
                headers={**self.auth_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=httpx.Timeout(wait_timeout),
            )
            elapsed = time.monotonic() - started
            body = _safe_json(resp)
            ok = resp.status_code == 200 and body.get("code", 0) == 0
            data = body.get("data") or {}
            detail = (
                f"status={resp.status_code} elapsed={elapsed:.1f}s "
                f"workflow_id={data.get('workflow_id')} run_status={data.get('status')}"
            )
            if not ok:
                detail += f" body={body}"
            self.record("POST /schema/upsert?wait=true", ok, detail)
            if ok:
                self._verify_schema_exists(client, upsert_name)
        except httpx.ReadTimeout:
            self.record(
                "POST /schema/upsert?wait=true",
                False,
                f"timeout after {wait_timeout}s — is Temporal up and worker running?",
            )
        except httpx.HTTPError as exc:
            self.record("POST /schema/upsert?wait=true", False, str(exc))

    def _verify_schema_exists(self, client: httpx.Client, name: str) -> None:
        try:
            resp = client.get(
                "/api/v1/schema/get",
                params={"name": name},
                headers=self.auth_headers(),
            )
            body = _safe_json(resp)
            ok = resp.status_code == 200 and (body.get("data") or {}).get("name") == name
            self.record("GET /schema/get (after upsert)", ok, f"name={name}")
        except httpx.HTTPError as exc:
            self.record("GET /schema/get (after upsert)", False, str(exc))

    def _check_dreaming_run(self, client: httpx.Client) -> None:
        job_id = self.settings.dreaming_job_id
        wait_timeout = self.settings.wait_timeout_sec + 10
        try:
            started = time.monotonic()
            resp = client.post(
                f"/api/v1/governance/dreaming/jobs/{job_id}/runs",
                params={"wait": "true"},
                headers=self.auth_headers(),
                timeout=httpx.Timeout(wait_timeout),
            )
            elapsed = time.monotonic() - started
            body = _safe_json(resp)
            ok = resp.status_code == 200 and body.get("code", 0) == 0
            data = body.get("data") or {}
            self.dreaming_run_uuid = data.get("run_uuid")
            detail = (
                f"status={resp.status_code} elapsed={elapsed:.1f}s "
                f"run_uuid={self.dreaming_run_uuid} wf_status={data.get('status')}"
            )
            if not ok:
                detail += f" body={body}"
            self.record(f"POST /governance/dreaming/jobs/{job_id}/runs", ok, detail)
            if ok and self.dreaming_run_uuid:
                self._check_dreaming_run_status(client)
        except httpx.ReadTimeout:
            self.record(
                f"POST /governance/dreaming/jobs/{job_id}/runs",
                False,
                f"timeout — Temporal worker required (poetry run memory-engine-worker)",
            )
        except httpx.HTTPError as exc:
            self.record(f"POST /governance/dreaming/jobs/{job_id}/runs", False, str(exc))

    def _check_dreaming_run_status(self, client: httpx.Client) -> None:
        assert self.dreaming_run_uuid
        try:
            resp = client.get(
                f"/api/v1/governance/dreaming/runs/{self.dreaming_run_uuid}",
                headers=self.auth_headers(),
            )
            body = _safe_json(resp)
            data = body.get("data") or {}
            status = data.get("status")
            ok = resp.status_code == 200 and status in ("succeeded", "running", "queued")
            self.record("GET /governance/dreaming/runs/{uuid}", ok, f"status={status}")
        except httpx.HTTPError as exc:
            self.record("GET /governance/dreaming/runs/{uuid}", False, str(exc))

    def _check_billing_events(self, client: httpx.Client) -> None:
        try:
            resp = client.get(
                "/api/v1/billing/events",
                params={"limit": 5},
                headers=self.auth_headers(),
            )
            body = _safe_json(resp)
            ok = resp.status_code == 200 and body.get("code", 0) == 0
            self.record("GET /billing/events", ok, f"status={resp.status_code}")
        except httpx.HTTPError as exc:
            self.record("GET /billing/events", False, str(exc))

    def _exit_code(self) -> int:
        print("-" * 60)
        passed = sum(1 for r in self.results if r.ok and not r.skipped)
        failed = sum(1 for r in self.results if not r.ok and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)
        print(f"Summary: {passed} passed, {failed} failed, {skipped} skipped")
        if failed:
            print("\nFailed steps:")
            for r in self.results:
                if not r.ok and not r.skipped:
                    print(f"  - {r.name}: {r.detail}")
            print(
                "\nHints:\n"
                "  • API: cd backend && poetry run uvicorn memory_engine.main:app --reload\n"
                "  • Worker: poetry run memory-engine-worker\n"
                "  • Temporal: cd infra/docker-compose && docker compose up -d temporal\n"
                "  • Skip workflows: E2E_SKIP_TEMPORAL=1 E2E_SKIP_DREAMING=1 python3 scripts/e2e_smoke.py"
            )
            return 1
        return 0


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return {"raw": resp.text[:500]}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MemoryEngine E2E smoke test")
    parser.add_argument("--base-url", default=None, help="Override API_BASE_URL")
    parser.add_argument("--api-key", default=None, help="Override MOS_API_KEY")
    parser.add_argument("--skip-temporal", action="store_true")
    parser.add_argument("--skip-dreaming", action="store_true")
    parser.add_argument("--wait-timeout", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = Settings()
    if args.base_url:
        settings.base_url = args.base_url.rstrip("/")
    if args.api_key:
        settings.api_key = args.api_key
    if args.skip_temporal:
        settings.skip_temporal = True
    if args.skip_dreaming:
        settings.skip_dreaming = True
    if args.wait_timeout is not None:
        settings.wait_timeout_sec = args.wait_timeout

    if not settings.disable_auth and not settings.api_key:
        print("ERROR: set MOS_API_KEY or APP_DISABLE_AUTH=true", file=sys.stderr)
        return 2

    return E2ERunner(settings).run()


if __name__ == "__main__":
    sys.exit(main())
