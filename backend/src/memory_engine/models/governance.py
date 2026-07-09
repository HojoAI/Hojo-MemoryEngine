"""Governance and Dreaming models."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CHAR, DateTime, Enum, Integer, JSON, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memory_engine.db.base import AuditMixin, Base


class DreamingJob(Base, AuditMixin):
    """Dreaming job definition."""

    __tablename__ = "dreaming_job"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(Enum("LIGHT", "REM", "DEEP", name="dream_tier"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    engine: Mapped[str] = mapped_column(Enum("spark", "flink", name="dream_engine"), nullable=False)
    task_template_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")


class DreamingJobRun(Base, AuditMixin):
    """Dreaming job run."""

    __tablename__ = "dreaming_job_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True, nullable=False)
    job_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    temporal_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    temporal_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    triggered_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class GovernanceProposal(Base, AuditMixin):
    """Governance proposal."""

    __tablename__ = "governance_proposal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_uuid: Mapped[str] = mapped_column(CHAR(36), unique=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    job_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    impact_scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    auto_apply: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class ProposalApproval(Base, AuditMixin):
    """Proposal approval record."""

    __tablename__ = "proposal_approval"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    approval_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approver_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class MemoryLock(Base, AuditMixin):
    """Memory lock."""

    __tablename__ = "memory_lock"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lock_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_ref_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    locked_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    triggered_by_proposal_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class WritebackAudit(Base, AuditMixin):
    """Writeback audit."""

    __tablename__ = "writeback_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    api_endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id_before: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_id_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    version_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rollback_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
