"""Integration tests for operational database seeder."""

import pytest
from sqlalchemy import func, select

from src.db.models import IncidentLog, InfraService
from src.db.seed import reset_database, seed_database
from src.db.session import session_scope


@pytest.mark.asyncio
async def test_seeder_execution_and_idempotency() -> None:
    """Verify that seed_database and reset_database execute idempotently."""
    # Run clean reset
    await reset_database()

    async with session_scope() as session:
        # 1. Verify 5 services exist
        services_res = await session.execute(select(InfraService))
        services = list(services_res.scalars().all())
        assert len(services) == 5

        service_names = {s.service_name for s in services}
        expected_services = {
            "payment-api",
            "redis-cache",
            "auth-service",
            "postgres-primary",
            "nginx-ingress",
        }
        assert service_names == expected_services

        # 2. Check Scenario A (payment-api)
        payment_svc = await session.get(InfraService, "payment-api")
        assert payment_svc is not None
        assert payment_svc.status == "DEGRADED"
        assert payment_svc.p95_latency_ms == 4200
        assert payment_svc.active_connections == 100
        assert payment_svc.db_pool_size == 100

        # Check Scenario B (redis-cache)
        redis_svc = await session.get(InfraService, "redis-cache")
        assert redis_svc is not None
        assert redis_svc.status == "CRITICAL"
        assert redis_svc.memory_usage_mb == 4090

        # Check Scenario C (auth-service)
        auth_svc = await session.get(InfraService, "auth-service")
        assert auth_svc is not None
        assert auth_svc.status == "DEGRADED"
        assert auth_svc.active_replicas == 2

        # 3. Verify logs exist for payment-api
        log_res = await session.execute(
            select(IncidentLog).where(
                IncidentLog.service_name == "payment-api",
                IncidentLog.error_code == "ERR_DB_POOL_EXHAUSTED",
            )
        )
        logs = list(log_res.scalars().all())
        assert len(logs) >= 2

        count_before = (
            await session.execute(select(func.count()).select_from(InfraService))
        ).scalar()
        assert count_before == 5

        log_count_before = (
            await session.execute(select(func.count()).select_from(IncidentLog))
        ).scalar()
        assert log_count_before == 8

    # 4. Re-run seed_database to verify idempotency (must not duplicate services or logs)
    await seed_database()

    async with session_scope() as session:
        count_after = (
            await session.execute(select(func.count()).select_from(InfraService))
        ).scalar()
        assert count_after == 5

        log_count_after = (
            await session.execute(select(func.count()).select_from(IncidentLog))
        ).scalar()
        assert log_count_after == 8
