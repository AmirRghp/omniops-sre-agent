"""Integration tests for database session, tables creation, and operations."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.db.models import IncidentLog, InfraService, RemediationExecution
from src.db.session import init_db, session_scope


@pytest.mark.asyncio
async def test_database_table_creation_and_crud() -> None:
    """Test creating tables, inserting models, and testing relationships."""
    await init_db()

    async with session_scope() as session:
        # Clean up any residual test data
        existing_test_svc = await session.get(InfraService, "test-integration-svc")
        if existing_test_svc:
            await session.delete(existing_test_svc)
            await session.commit()

    async with session_scope() as session:
        # 1. Insert an infrastructure service
        test_svc = InfraService(
            service_name="test-integration-svc",
            status="DEGRADED",
            cpu_usage_pct=Decimal("88.50"),
            memory_usage_mb=2048,
            memory_limit_mb=4096,
            p95_latency_ms=1500,
            active_replicas=2,
            max_replicas=6,
            db_pool_size=100,
            active_connections=95,
        )
        session.add(test_svc)

        # 2. Insert an incident log associated with the service
        test_log = IncidentLog(
            service_name="test-integration-svc",
            severity="ERROR",
            error_code="ERR_DB_POOL_EXHAUSTED",
            message="Connection pool at 95% threshold",
            trace_id="tr-test-12345",
        )
        session.add(test_log)

        # 3. Insert a remediation record
        test_remediation = RemediationExecution(
            idempotency_key=f"idem_test_{uuid.uuid4().hex[:8]}",
            thread_id="th_test_001",
            service_name="test-integration-svc",
            action_type="increase_db_pool",
            parameters={"db_pool_size": 200},
            reason="High connection pool exhaustion",
            approval_status="PENDING",
        )
        session.add(test_remediation)

    # 4. Query back and verify
    async with session_scope() as session:
        queried_svc = await session.get(InfraService, "test-integration-svc")
        assert queried_svc is not None
        assert queried_svc.status == "DEGRADED"
        assert queried_svc.cpu_usage_pct == Decimal("88.50")

        # Query incident log
        log_stmt = select(IncidentLog).where(
            IncidentLog.service_name == "test-integration-svc"
        )
        result = await session.execute(log_stmt)
        logs = list(result.scalars().all())
        assert len(logs) >= 1
        assert logs[0].error_code == "ERR_DB_POOL_EXHAUSTED"

        # 4. Cascade delete service and ensure log is deleted
        # First delete remediation execution since it references infra_services without cascade
        rem_stmt = select(RemediationExecution).where(
            RemediationExecution.service_name == "test-integration-svc"
        )
        rem_res = await session.execute(rem_stmt)
        for rem in rem_res.scalars().all():
            await session.delete(rem)
        await session.flush()

        await session.delete(queried_svc)

    # 5. Verify cascade deletion
    async with session_scope() as session:
        log_check = await session.execute(
            select(IncidentLog).where(IncidentLog.service_name == "test-integration-svc")
        )
        assert len(list(log_check.scalars().all())) == 0


@pytest.mark.asyncio
async def test_session_rollback_on_exception() -> None:
    """Test session rolls back changes when an exception is raised within scope."""
    await init_db()

    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            test_svc = InfraService(
                service_name="rollback-svc",
                status="HEALTHY",
                cpu_usage_pct=Decimal("10.00"),
                memory_usage_mb=512,
                memory_limit_mb=1024,
                p95_latency_ms=50,
                active_replicas=1,
                max_replicas=2,
            )
            session.add(test_svc)
            raise RuntimeError("Forced simulation error")

    async with session_scope() as session:
        svc = await session.get(InfraService, "rollback-svc")
        assert svc is None
