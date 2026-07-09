"""Dashboard onboarding: API keys and tenant self-service."""

from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyApplyRequest(BaseModel):
    """Apply for a new API key (Supabase user or admin-assisted)."""

    name: str = Field(default="dashboard", max_length=128)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)


class ApiKeyCreateRequest(BaseModel):
    """Create an additional API key for the current tenant (authenticated)."""

    name: str = Field(default="default", max_length=128)


class ApiKeySummary(BaseModel):
    """API key metadata (never includes plaintext secret)."""

    id: int
    name: str
    key_prefix: str
    tenant_id: int
    org_id: int
    user_id: int
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    create_time: datetime | None = None


class ApiKeyIssueResponse(BaseModel):
    """Newly issued API key — plaintext shown once."""

    tenant_id: int
    org_id: int
    user_id: int
    api_key_id: int
    api_key: str
    key_prefix: str


class OnboardingProfileResponse(BaseModel):
    """Current Supabase-linked Memory Engine user profile."""

    tenant_id: int
    org_id: int
    user_id: int
    email: str
    display_name: str | None
    tenant_code: str | None = None
    org_code: str | None = None
    api_keys: list[ApiKeySummary] = Field(default_factory=list)
