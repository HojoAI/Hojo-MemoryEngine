"""End-user user APIs: list/delete all memory data."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.config import get_settings
from memory_engine.db.session import get_db
from memory_engine.main import app
from memory_engine.schemas.memory_field import (
    UserMemoryDataDeleteResult,
    UserMemoryDataExistsResult,
    UserMemoryDataListResult,
)


async def _mock_get_db():
    yield AsyncMock()

END_USER_ID = "1234567890"
END_USER_TOKEN = "test-h5-user-token"


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
    }


@pytest.mark.asyncio
async def test_user_list_all_requires_end_user_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/data/user/list-all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "ILLEGAL_ARGUMENT"
    assert "X-User-Id" in body["resMessage"]


@pytest.mark.asyncio
async def test_user_list_all_rejects_service_bearer() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/data/user/list-all",
            json={"memory_user_id": "mos_partition_abc"},
            headers={
                "Authorization": "Bearer some-service-token",
                "X-Tenant-Id": "1",
            },
        )
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_user_has_data_requires_end_user_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/data/user/has-data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "ILLEGAL_ARGUMENT"
    assert "X-User-Id" in body["resMessage"]


@pytest.mark.asyncio
async def test_user_has_data_with_end_user_headers() -> None:
    exists_result = UserMemoryDataExistsResult(
        memory_user_id=END_USER_ID,
        has_data=True,
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
            "memory_engine.api.v1.data_routes.data_service.user_has_memory_data",
            new_callable=AsyncMock,
            return_value=exists_result,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/data/user/has-data",
                headers=_end_user_headers(),
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"]["memory_user_id"] == END_USER_ID
    assert body["resContent"]["has_data"] is True


@pytest.mark.asyncio
async def test_user_has_data_returns_false_when_empty() -> None:
    exists_result = UserMemoryDataExistsResult(
        memory_user_id=END_USER_ID,
        has_data=False,
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
            "memory_engine.api.v1.data_routes.data_service.user_has_memory_data",
            new_callable=AsyncMock,
            return_value=exists_result,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/data/user/has-data",
                headers=_end_user_headers(),
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"]["has_data"] is False


@pytest.mark.asyncio
async def test_user_list_all_get_with_end_user_headers() -> None:
    list_result = UserMemoryDataListResult(
        memory_user_id=END_USER_ID,
        items=[],
        total=0,
        offset=0,
        limit=10,
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
            "memory_engine.api.v1.data_routes.data_service.list_all_for_user",
            new_callable=AsyncMock,
            return_value=list_result,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/data/user/list-all",
                params={"offset": 0, "limit": 10},
                headers=_end_user_headers(),
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"] is not None
    assert body["resContent"]["memory_user_id"] == END_USER_ID
    assert "items" in body["resContent"]


@pytest.mark.asyncio
async def test_user_delete_all_with_end_user_headers() -> None:
    delete_result = UserMemoryDataDeleteResult(
        memory_user_id=END_USER_ID,
        deleted_count=0,
        vector_marked_count=0,
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
            "memory_engine.api.v1.data_routes.data_service.delete_all_for_user",
            new_callable=AsyncMock,
            return_value=delete_result,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/data/user/delete-all",
                headers={**_end_user_headers(), "Content-Type": "application/json"},
                json={},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"]["memory_user_id"] == END_USER_ID
