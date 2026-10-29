"""Unit tests for SQLAlchemy 2.0 ORM models and constraints."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, Index

from src.db.models import Base, IncidentLog, InfraService, RemediationExecution


def test_models_metadata_registration() -> None:
    """Test that all three tables are properly registered in declarative Base."""
    table_names = set(Base.metadata.tables.keys())
    assert "infra_services" in table_names
    assert "incident_logs" in table_names
    assert "remediation_executions" in table_names


def test_infra_service_model_attributes() -> None:
    """Test column names, types, and constraints on InfraService."""
    table = InfraService.__table__
    assert table.c.service_name.primary_key is True
    assert table.c.status.nullable is False
    assert table.c.cpu_usage_pct.nullable is False
    assert table.c.db_pool_size.default is not None
    assert table.c.db_pool_size.default.arg == 100
    assert table.c.active_connections.default is not None
    assert table.c.active_connections.default.arg == 20

    check_constraints = [c for c in getattr(table, "constraints", set()) if isinstance(c, CheckConstraint)]
    assert any("HEALTHY" in str(c.sqltext) for c in check_constraints)

    service = InfraService(
        service_name="payment-api",
        status="HEALTHY",
        cpu_usage_pct=Decimal("45.50"),
        memory_usage_mb=1024,
        memory_limit_mb=2048,
        p95_latency_ms=120,
        active_replicas=3,
        max_replicas=10,
    )
    assert service.service_name == "payment-api"
    assert service.status == "HEALTHY"


def test_incident_log_model_attributes() -> None:
    """Test columns, foreign keys, and indexes on IncidentLog."""
    table = IncidentLog.__table__
    assert table.c.id.primary_key is True
    assert table.c.service_name.nullable is False
    assert table.c.severity.nullable is False
    assert table.c.error_code.nullable is False
    assert table.c.message.nullable is False

    fk = list(table.foreign_keys)[0]
    assert fk.target_fullname == "infra_services.service_name"
    assert fk.ondelete == "CASCADE"

    indices = {idx.name for idx in getattr(table, "indexes", set()) if isinstance(idx, Index)}
    assert "idx_incident_logs_service_severity" in indices
    assert "idx_incident_logs_error_code" in indices


def test_remediation_execution_model_attributes() -> None:
    """Test columns and constraints on RemediationExecution."""
    table = RemediationExecution.__table__
    assert table.c.id.primary_key is True
    assert table.c.idempotency_key.unique is True
    assert table.c.thread_id.nullable is False
    assert table.c.action_type.nullable is False
    assert table.c.reason.nullable is False
    assert table.c.approval_status.nullable is False

    indices = {idx.name for idx in getattr(table, "indexes", set()) if isinstance(idx, Index)}
    assert "idx_remediation_idempotency" in indices
