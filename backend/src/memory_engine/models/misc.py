"""Miscellaneous models."""

from datetime import datetime

from sqlalchemy import BigInteger, CHAR, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class SecretRef(Base, AuditMixin):
    """Secret reference metadata."""

    __tablename__ = "secret_ref"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    secret_name: Mapped[str] = mapped_column(String(128), nullable=False)
    vault_path: Mapped[str] = mapped_column(String(512), nullable=False)
    secret_type: Mapped[str] = mapped_column(String(32), nullable=False)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    rotation_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LlmProvider(Base, AuditMixin):
    """LLM provider."""

    __tablename__ = "llm_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    default_model: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_secret_ref: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extra_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class SchemaChangelog(Base, AuditMixin):
    """Schema changelog."""

    __tablename__ = "schema_changelog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    change_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_action: Mapped[str] = mapped_column(String(16), nullable=False)
    version_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IdempotencyRecord(Base, AuditMixin):
    """Idempotency record."""

    __tablename__ = "idempotency_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
