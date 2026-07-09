"""Request-scoped tenant and auth context."""

from dataclasses import dataclass, field


@dataclass
class RequestContext:
    """Per-request identity and tenant scope."""

    tenant_id: int
    org_id: int = 0
    user_id: int | None = None
    api_key_id: int | None = None
    permissions: set[str] = field(default_factory=set)
    trace_id: str | None = None
