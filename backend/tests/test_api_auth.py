"""API key authentication tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext

from memory_engine.config import get_settings
from memory_engine.db import session as db_session
from memory_engine.main import app
from memory_engine.models.auth import ApiKey

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
DEV_KEY = "mos_devtest00001ab"


@pytest.fixture(autouse=True)
def enable_api_key_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DISABLE_AUTH", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_api_key() -> ApiKey:
    row = ApiKey()
    row.id = 1
    row.tenant_id = 1
    row.org_id = 1
    row.user_id = 1
    row.key_prefix = DEV_KEY[:16]
    row.key_hash = pwd.hash(DEV_KEY)
    row.deleted = 0
    row.revoked_at = None
    row.expires_at = None
    row.permissions_json = {
        "allow": ["schema:*", "data:*", "governance:*", "billing:read", "billing:write"]
    }
    return row


@pytest.mark.asyncio
async def test_schema_list_requires_bearer() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/schema/list")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_schema_list_with_valid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_api_key()

    class _Scalars:
        def all(self):
            return []

    class _Result:
        def scalar_one_or_none(self):
            return fake

        def scalars(self):
            return _Scalars()

    class _Session:
        async def execute(self, *_args, **_kwargs):
            return _Result()

    async def _override_db():
        yield _Session()

    app.dependency_overrides[db_session.get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/schema/list",
                headers={"Authorization": f"Bearer {DEV_KEY}"},
            )
        assert resp.status_code != 403
    finally:
        app.dependency_overrides.clear()
