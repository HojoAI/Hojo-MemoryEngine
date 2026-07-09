"""Tenant and user models."""

from datetime import datetime

from sqlalchemy import BigInteger, Enum, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class Tenant(Base, AuditMixin):
    """Tenant table."""

    __tablename__ = "tenant"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "suspended", "archived", name="tenant_status"),
        nullable=False,
        default="active",
    )
    settings_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Organization(Base, AuditMixin):
    """Organization table."""

    __tablename__ = "organization"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "suspended", "archived", name="org_status"),
        nullable=False,
        default="active",
    )


class AppUser(Base, AuditMixin):
    """Application user."""

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    supabase_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "disabled", name="user_status"),
        nullable=False,
        default="active",
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
