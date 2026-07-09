"""Workflow input/output dataclasses."""

from dataclasses import dataclass
from typing import Any


@dataclass
class SchemaUpsertInput:
    """Schema upsert workflow payload."""

    tenant_id: int
    org_id: int
    user_id: int | None
    name: str
    create_payload: dict[str, Any]
    update_payload: dict[str, Any] | None = None


@dataclass
class SchemaCrudInput:
    """Schema create/update/delete workflow."""

    tenant_id: int
    org_id: int
    user_id: int | None
    operation: str
    name: str
    create_payload: dict[str, Any] | None = None
    update_payload: dict[str, Any] | None = None


@dataclass
class DataWriteInput:
    """Memory data write workflow."""

    tenant_id: int
    org_id: int
    user_id: int | None
    create_payload: dict[str, Any]


@dataclass
class DreamingRunInput:
    """Dreaming job run workflow payload."""

    run_uuid: str
    job_id: int
    tenant_id: int
    org_id: int
    user_id: int | None
    job_name: str
    tier: str
    engine: str
    config_json: dict[str, Any] | None = None
