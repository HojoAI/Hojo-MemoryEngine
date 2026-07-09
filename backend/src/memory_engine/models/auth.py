"""Auth models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class ApiKey(Base, AuditMixin):
    """API key."""

    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    scope_org_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    permissions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class Permission(Base, AuditMixin):
    """Permission dictionary."""

    __tablename__ = "permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    permission_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Role(Base, AuditMixin):
    """Role."""

    __tablename__ = "role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role_type: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
