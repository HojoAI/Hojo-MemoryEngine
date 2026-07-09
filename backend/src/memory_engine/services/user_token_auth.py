"""End-user token validation (Redis or account HTTP)."""

import json
import secrets

import httpx

from memory_engine.config import get_settings
from memory_engine.core.user_api_errors import UserApiError
from memory_engine.integrations.redis_cache import get_redis


async def validate_user_token(user_id: str, token: str) -> None:
    """Validate ``X-User-Token`` for the given ``X-User-Id``.

    Raises:
        UserApiError: Missing configuration, invalid or expired token.
    """
    settings = get_settings()
    if settings.user_token_skip_validate or settings.app_disable_auth:
        return

    template = settings.user_token_redis_key_template.strip()
    if template:
        key = template.format(user_id=user_id, token=token)
        r = await get_redis()
        stored = await r.get(key)
        if stored is None:
            raise UserApiError("UNAUTHORIZED", "无效或已过期的用户 Token")
        raw = stored.decode() if isinstance(stored, bytes) else str(stored)
        if not _token_matches(raw, token):
            raise UserApiError("UNAUTHORIZED", "无效或已过期的用户 Token")
        return

    validate_url = settings.user_account_validate_url.strip()
    if validate_url:
        async with httpx.AsyncClient(timeout=settings.user_account_validate_timeout_seconds) as client:
            resp = await client.get(
                validate_url,
                headers={"X-User-Id": user_id, "X-User-Token": token},
            )
        if resp.status_code == 401:
            raise UserApiError("UNAUTHORIZED", "无效或已过期的用户 Token")
        if resp.status_code >= 400:
            raise UserApiError("GENERAL_ERROR", "用户 Token 校验失败")
        try:
            body = resp.json()
        except json.JSONDecodeError:
            return
        res_code = str(body.get("resCode", ""))
        if res_code not in ("OK", "200"):
            msg = body.get("resMessage") or "无效或已过期的用户 Token"
            raise UserApiError("UNAUTHORIZED", str(msg))
        return

    raise UserApiError(
        "GENERAL_ERROR",
        "用户 Token 校验未配置（设置 USER_TOKEN_REDIS_KEY_TEMPLATE 或 "
        "USER_ACCOUNT_VALIDATE_URL，开发环境可 USER_TOKEN_SKIP_VALIDATE=true）",
    )


def _token_matches(stored: str, presented: str) -> bool:
    """Compare token from Redis (plain string or JSON with userToken field)."""
    stored = stored.strip()
    if stored == presented:
        return True
    if stored.startswith("{"):
        try:
            data = json.loads(stored)
        except json.JSONDecodeError:
            return False
        for key in ("userToken", "token", "accessToken"):
            val = data.get(key)
            if isinstance(val, str) and secrets.compare_digest(val, presented):
                return True
    return secrets.compare_digest(stored, presented)
