"""Billing models."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CHAR, Date, DateTime, Enum, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class BillingEvent(Base, AuditMixin):
    """Billing event."""

    __tablename__ = "billing_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    api_key_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    llm_provider_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class UsageQuota(Base, AuditMixin):
    """Usage quota."""

    __tablename__ = "usage_quota"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quota_type: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    quota_limit: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    quota_used: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class BillingInvoice(Base, AuditMixin):
    """Billing invoice."""

    __tablename__ = "billing_invoice"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    period_month: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    period_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
