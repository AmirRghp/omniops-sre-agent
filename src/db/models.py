"""SQLAlchemy 2.0 async models for OmniOps SRE Agent."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base class for all operational models."""

    pass


class InfraService(Base):
    """Monitored infrastructure microservices and their live metrics."""

    __tablename__ = "infra_services"

    service_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    cpu_usage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    memory_usage_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    p95_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    active_replicas: Mapped[int] = mapped_column(Integer, nullable=False)
    max_replicas: Mapped[int] = mapped_column(Integer, nullable=False)
    db_pool_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active_connections: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    last_restarted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    logs: Mapped[list["IncidentLog"]] = relationship(
        "IncidentLog",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    remediations: Mapped[list["RemediationExecution"]] = relationship(
        "RemediationExecution",
        back_populates="service",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('HEALTHY', 'DEGRADED', 'CRITICAL', 'RESTARTING')",
            name="ck_infra_services_status",
        ),
    )


class IncidentLog(Base):
    """Operational telemetry logs and error codes for incident triage."""

    __tablename__ = "incident_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    service_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("infra_services.service_name", ondelete="CASCADE"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    service: Mapped["InfraService"] = relationship(
        "InfraService",
        back_populates="logs",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARN', 'ERROR', 'CRITICAL')",
            name="ck_incident_logs_severity",
        ),
        Index("idx_incident_logs_service_severity", "service_name", "severity", created_at.desc()),
        Index("idx_incident_logs_error_code", "error_code"),
    )


class RemediationExecution(Base):
    """Audit and idempotency ledger for infrastructure remediation actions."""

    __tablename__ = "remediation_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("infra_services.service_name", ondelete="CASCADE"),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    service: Mapped["InfraService"] = relationship(
        "InfraService",
        back_populates="remediations",
    )

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('restart_service', 'scale_replicas', "
            "'flush_redis_cache', 'increase_db_pool')",
            name="ck_remediation_action_type",
        ),
        CheckConstraint(
            "approval_status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_remediation_approval_status",
        ),
        Index("idx_remediation_idempotency", "idempotency_key", unique=True),
    )
