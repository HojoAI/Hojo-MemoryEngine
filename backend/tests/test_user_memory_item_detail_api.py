"""Tests for user memory item detail API."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.config import get_settings
from memory_engine.db.session import get_db
from memory_engine.main import app
from memory_engine.schemas.user_memory_item import (
    UserMemoryGenerationBasisOut,
    UserMemoryItemDetailOut,
)


async def _mock_get_db():
    yield AsyncMock()


END_USER_ID = "1234567890"
END_USER_TOKEN = "test-h5-user-token"
ITEM_ID = "abc123detail"


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
async def test_user_detail_requires_item_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/data/user/detail",
            headers=_end_user_headers(),
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_user_detail_success() -> None:
    detail = UserMemoryItemDetailOut(
        item_id=ITEM_ID,
        user_id=END_USER_ID,
        dimension="goal",
        dimension_label="短期目标",
        status="confirmed",
        status_label="启用中",
        content="用户计划在 6 月底前完成会员体系方案",
        time="2026-05-21 09:15",
        memory_field_name="短期目标",
        generation_basis=UserMemoryGenerationBasisOut(
            source="dialogue",
            source_label="主对话",
            record_time="2026-05-20",
        ),
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
            "memory_engine.api.v1.data_routes.user_list_service.get_user_memory_item_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/data/user/detail",
                params={"itemId": ITEM_ID},
                headers=_end_user_headers(),
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    content = body["resContent"]
    assert content["itemId"] == ITEM_ID
    assert content["dimensionLabel"] == "短期目标"
    assert content["statusLabel"] == "启用中"
    assert content["generationBasis"]["sourceLabel"] == "主对话"
    assert content["generationBasis"]["recordTime"] == "2026-05-20"
    assert "recentlyUsed" not in content
    assert "generationMethod" not in content.get("generationBasis", {})
