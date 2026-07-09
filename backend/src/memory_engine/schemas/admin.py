"""Admin bootstrap API schemas."""

from pydantic import BaseModel, Field


class TenantBootstrapRequest(BaseModel):
    """Create tenant + org + user + API key in one call."""

    tenant_code: str = Field(..., max_length=64)
    tenant_name: str = Field(..., max_length=255)
    org_code: str = Field(..., max_length=64)
    org_name: str = Field(..., max_length=255)
    email: str = Field(..., max_length=320)
    display_name: str | None = None
    api_key_name: str = "default"
    supabase_user_id: str | None = Field(default=None, max_length=128)


class TenantBootstrapResponse(BaseModel):
    """Bootstrap result — api_key shown once."""

    tenant_id: int
    org_id: int
    user_id: int
    api_key_id: int
    api_key: str
    key_prefix: str
