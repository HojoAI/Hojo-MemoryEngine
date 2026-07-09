"""Schema-related ORM models."""

from sqlalchemy import BigInteger, Enum, Integer, JSON, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class MemoryField(Base, AuditMixin):
    """Memory field (schema) definition."""

    __tablename__ = "memory_field"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    value_type: Mapped[str] = mapped_column(
        Enum("string", "number", "boolean", "json", "array", "text", name="mf_value_type"),
        nullable=False,
        default="string",
    )
    match_method: Mapped[str] = mapped_column(
        Enum("OVERWRITE", "APPEND", "MERGE", name="mf_match_method"),
        nullable=False,
        default="OVERWRITE",
    )
    storage_type: Mapped[str] = mapped_column(
        Enum("KV", "VECTOR", "KV_AND_VECTOR", name="mf_storage_type"),
        nullable=False,
        default="KV",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        Enum("active", "deprecated", name="mf_status"),
        nullable=False,
        default="active",
    )
    source: Mapped[str] = mapped_column(
        Enum("dashboard", "sdk", "dreaming", "api", name="mf_source"),
        nullable=False,
        default="api",
    )


class CapabilityRegistry(Base, AuditMixin):
    """Capability registry."""

    __tablename__ = "capability_registry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    capability_name: Mapped[str] = mapped_column(String(128), nullable=False)
    module_name: Mapped[str] = mapped_column(String(255), nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_kind: Mapped[str] = mapped_column(
        Enum("parse", "retrieve", "call", name="cap_rule_kind"),
        nullable=False,
    )
    slot_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_provider_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_seen_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    heartbeat_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    code_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ParseRule(Base, AuditMixin):
    """Parse rule."""

    __tablename__ = "parse_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    memory_field_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    memory_field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_type: Mapped[str] = mapped_column(
        Enum("builtin", "custom", name="parse_rule_type"),
        nullable=False,
        default="custom",
    )
    rule_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(
        Enum("dashboard", "sdk", "dreaming", "api", name="parse_source"),
        nullable=False,
        default="api",
    )


class RetrieveRule(Base, AuditMixin):
    """Retrieve rule."""

    __tablename__ = "retrieve_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    memory_field_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memory_field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    retrieve_method: Mapped[str] = mapped_column(
        Enum("EXACT", "REGEX", "SEMANTIC", "LLM", name="retrieve_method"),
        nullable=False,
    )
    capability_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_type: Mapped[str] = mapped_column(
        Enum("builtin", "custom", name="retrieve_rule_type"),
        nullable=False,
        default="custom",
    )
    rule_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(
        Enum("dashboard", "sdk", "dreaming", "api", name="retrieve_source"),
        nullable=False,
        default="api",
    )


class MergeRule(Base, AuditMixin):
    """Merge rule (LLM fusion when match_method=MERGE)."""

    __tablename__ = "merge_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    memory_field_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    memory_field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(
        Enum("dashboard", "sdk", "dreaming", "api", name="merge_source"),
        nullable=False,
        default="api",
    )


class CallRule(Base, AuditMixin):
    """Call rule."""

    __tablename__ = "call_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    memory_field_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memory_field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    slot_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_type: Mapped[str] = mapped_column(
        Enum("builtin", "custom", name="call_rule_type"),
        nullable=False,
        default="custom",
    )
    rule_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(
        Enum("dashboard", "sdk", "dreaming", "api", name="call_source"),
        nullable=False,
        default="api",
    )
