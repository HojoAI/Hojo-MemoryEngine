"""Onboarding API tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext

from memory_engine.config import get_settings
from memory_engine.db import session as db_session
from memory_engine.main import app
from memory_engine.models.auth import ApiKey
from memory_engine.models.tenant import AppUser

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
DEV_KEY = "mos_devtest00001ab"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DISABLE_AUTH", "false")
    monkeypatch.setenv("ONBOARDING_ALLOW_SELF_REGISTER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_apply_requires_supabase_header() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/onboarding/api-key/apply",
            json={"email": "new@example.com", "name": "test"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_api_keys_with_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_key = ApiKey()
    fake_key.id = 1
    fake_key.tenant_id = 1
    fake_key.org_id = 1
    fake_key.user_id = 1
    fake_key.key_prefix = DEV_KEY[:16]
    fake_key.key_hash = pwd.hash(DEV_KEY)
    fake_key.name = "dev"
    fake_key.deleted = 0
    fake_key.revoked_at = None
    fake_key.permissions_json = {"allow": ["api_key:manage", "schema:*"]}

    class _Scalars:
        def all(self):
            return [fake_key]

    class _Result:
        def scalar_one_or_none(self):
            return fake_key

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
                "/api/v1/onboarding/api-keys",
                headers={
                    "Authorization": f"Bearer {DEV_KEY}",
                    "X-Tenant-Id": "1",
                    "X-Org-Id": "1",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["data"][0]["key_prefix"] == DEV_KEY[:16]
    finally:
        app.dependency_overrides.clear()
