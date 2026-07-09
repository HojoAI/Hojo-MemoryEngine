"""Tests for user memory list API (memory_data granularity, no splitting)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from memory_engine.config import get_settings
from memory_engine.db.session import get_db
from memory_engine.main import app
from memory_engine.schemas.user_memory_item import UserMemoryItemListPage, UserMemoryItemOut, format_memory_value


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


def test_format_memory_value_keeps_merged_text() -> None:
    assert format_memory_value("条目一；条目二;条目三") == "条目一；条目二;条目三"


def test_format_memory_value_single() -> None:
    assert format_memory_value("单条记忆") == "单条记忆"


def test_format_memory_value_append_list_matches_dashboard() -> None:
    assert format_memory_value(["开会", "通勤"]) == '["开会","通勤"]'


@pytest.mark.asyncio
async def test_user_list_requires_end_user_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/data/user/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "ILLEGAL_ARGUMENT"
    assert "X-User-Id" in body["resMessage"]


@pytest.mark.asyncio
async def test_user_list_with_filters() -> None:
    page = UserMemoryItemListPage(
        page_id=1,
        page_size=10,
        total_count=1,
        page_content=[
            UserMemoryItemOut(
                item_id="abc",
                user_id=END_USER_ID,
                dimension="background",
                dimension_label="背景知识习惯",
                source="dialogue",
                source_label="对话",
                status="confirmed",
                status_label="已确认",
                content="条目一；条目二",
                memory_field_name="背景知识习惯",
                created_at="2026-05-18T00:00:00+00:00",
                updated_at="2026-05-18T00:00:00+00:00",
            )
        ],
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
            "memory_engine.api.v1.data_routes.user_list_service.list_user_memory_items_page",
            new_callable=AsyncMock,
            return_value=page,
        ) as list_mock,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/data/user/list",
                params={
                    "pageId": 1,
                    "pageSize": 10,
                    "dimension": "background",
                    "source": "dialogue",
                    "status": "confirmed",
                    "keyword": "CRSPY",
                    "startTime": "2026-05-01",
                    "endTime": "2026-05-31",
                },
                headers=_end_user_headers(),
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resCode"] == "OK"
    assert body["resContent"]["pageId"] == 1
    assert body["resContent"]["pageSize"] == 10
    assert body["resContent"]["totalCount"] == 1
    assert body["resContent"]["pageContent"][0]["content"] == "条目一；条目二"
    list_mock.assert_awaited_once()
    kwargs = list_mock.await_args.kwargs
    assert kwargs["dimension"] == "background"
    assert kwargs["source"] == "dialogue"
    assert kwargs["status"] == "confirmed"
    assert kwargs["keyword"] == "CRSPY"
    assert kwargs["start_time"] == "2026-05-01"
    assert kwargs["end_time"] == "2026-05-31"
