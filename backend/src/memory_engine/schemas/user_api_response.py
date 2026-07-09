"""End-user API response envelope."""

from typing import Any

from pydantic import BaseModel, Field


class UserApiResponse(BaseModel):
    """Standard end-user response (``resCode`` / ``resMessage`` / ``resContent``)."""

    resCode: str = Field("OK", description="Business status code")
    resMessage: str = Field("请求成功", description="Human-readable message")
    resContent: Any = None


def user_api_ok(res_content: Any = None, res_message: str = "请求成功") -> UserApiResponse:
    """Success envelope."""
    return UserApiResponse(resCode="OK", resMessage=res_message, resContent=res_content)


def user_api_error(res_code: str, res_message: str) -> UserApiResponse:
    """Error envelope (still typically HTTP 200)."""
    return UserApiResponse(resCode=res_code, resMessage=res_message, resContent=None)
