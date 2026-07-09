"""End-user export-email API."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.config import get_settings
from memory_engine.db.session import get_db
from memory_engine.main import app
from memory_engine.schemas.memory_field import UserMemoryExportEmailResult

END_USER_ID = "1234567890"
END_USER_TOKEN = "test-h5-user-token"
EXPORT_EMAIL = "user@example.com"


async def _mock_get_db():
    yield AsyncMock()


@pytest.fixture(autouse=True)
def end_user_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_TOKEN_SKIP_VALIDATE", "true")
    monkeypatch.setenv("END_USER_DEFAULT_TENANT_ID", "1")
    monkeypatch.setenv("END_USER_DEFAULT_ORG_ID", "0")
    monkeypatch.setenv("APP_DISABLE_AUTH", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = _mock_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def _end_user_headers() -> dict[str, str]:
    return {
        "X-User-Id": END_USER_ID,
        "X-User-Token": END_USER_TOKEN,
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_export_email_requires_email() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/data/user/export-email",
            headers={**_end_user_headers(), "X-Tenant-Id": "1"},
            json={"offset": 0},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "ILLEGAL_ARGUMENT"


@pytest.mark.asyncio
async def test_export_email_success() -> None:
    export_result = UserMemoryExportEmailResult(
        email=EXPORT_EMAIL,
        memory_user_id=END_USER_ID,
        item_count=2,
        total=2,
        offset=0,
        limit=2,
    )
    with (
        patch(
            "memory_engine.api.deps.resolve_end_user_tenant_org",
            new_callable=AsyncMock,
            return_value=(1, 0),
        ),
        patch(
            "memory_engine.api.v1.data_routes.resolve_end_user_memory_user_id",
            new_callable=AsyncMock,
            return_value=END_USER_ID,
        ),
        patch(
            "memory_engine.api.v1.data_routes.export_memory_data_to_email",
            new_callable=AsyncMock,
            return_value=export_result,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/data/user/export-email",
                headers=_end_user_headers(),
                json={"email": EXPORT_EMAIL, "offset": 0, "limit": 200},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"]["email"] == EXPORT_EMAIL
    assert body["resContent"]["item_count"] == 2
