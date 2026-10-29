"""Operational database seeder for OmniOps SRE Agent.

Populates baseline infrastructure microservices and realistic incident scenarios
as specified in docs/DATABASE.md and docs/UX_FLOWS.md.
"""

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logger import setup_logger
from src.db.models import IncidentLog, InfraService, RemediationExecution
from src.db.session import engine, init_db, session_scope

logger = setup_logger("omniops.seeder")


async def seed_services(session: AsyncSession) -> dict[str, InfraService]:
    """Seed the 5 standard microservices with realistic operational states."""
    services_data = [
        # Scenario A: payment-api (DEGRADED, pool exhausted, high latency)
        InfraService(
            service_name="payment-api",
            status="DEGRADED",
            cpu_usage_pct=Decimal("38.50"),
            memory_usage_mb=1840,
            memory_limit_mb=2048,
            p95_latency_ms=4200,
            active_replicas=3,
            max_replicas=10,
            db_pool_size=100,
            active_connections=100,
            last_restarted_at=datetime.now(UTC),
        ),
        # Scenario B: redis-cache (CRITICAL, OOM eviction)
        InfraService(
            service_name="redis-cache",
            status="CRITICAL",
            cpu_usage_pct=Decimal("62.10"),
            memory_usage_mb=4090,
            memory_limit_mb=4096,
            p95_latency_ms=280,
            active_replicas=1,
            max_replicas=1,
            db_pool_size=50,
            active_connections=45,
            last_restarted_at=datetime.now(UTC),
        ),
        # Scenario C: auth-service (DEGRADED, CPU throttled, needs scaling)
        InfraService(
            service_name="auth-service",
            status="DEGRADED",
            cpu_usage_pct=Decimal("96.50"),
            memory_usage_mb=820,
            memory_limit_mb=1024,
            p95_latency_ms=1850,
            active_replicas=2,
            max_replicas=8,
            db_pool_size=80,
            active_connections=35,
            last_restarted_at=datetime.now(UTC),
        ),
        # Healthy Service 1: postgres-primary
        InfraService(
            service_name="postgres-primary",
            status="HEALTHY",
            cpu_usage_pct=Decimal("24.00"),
            memory_usage_mb=3100,
            memory_limit_mb=8192,
            p95_latency_ms=45,
            active_replicas=1,
            max_replicas=1,
            db_pool_size=200,
            active_connections=115,
            last_restarted_at=datetime.now(UTC),
        ),
        # Healthy Service 2: nginx-ingress
        InfraService(
            service_name="nginx-ingress",
            status="HEALTHY",
            cpu_usage_pct=Decimal("18.20"),
            memory_usage_mb=512,
            memory_limit_mb=2048,
            p95_latency_ms=85,
            active_replicas=2,
            max_replicas=6,
            db_pool_size=50,
            active_connections=15,
            last_restarted_at=datetime.now(UTC),
        ),
    ]

    services_map: dict[str, InfraService] = {}
    for svc in services_data:
        merged = await session.merge(svc)
        services_map[merged.service_name] = merged

    await session.flush()
    return services_map


async def seed_incident_logs(session: AsyncSession) -> None:
    """Populate realistic operational error logs idempotently by trace_id."""
    logs_data = [
        # Scenario A logs: payment-api
        IncidentLog(
            service_name="payment-api",
            severity="ERROR",
            error_code="ERR_DB_POOL_EXHAUSTED",
            message=(
                "QueuePool limit of size 100 overflow 0 reached, "
                "connection timed out, timeout 30.00"
            ),
            trace_id="tr-pay-98124a",
        ),
        IncidentLog(
            service_name="payment-api",
            severity="CRITICAL",
            error_code="ERR_DB_POOL_EXHAUSTED",
            message="Unable to acquire connection from pool for transaction checkout_order_99812",
            trace_id="tr-pay-98125b",
        ),
        IncidentLog(
            service_name="payment-api",
            severity="WARN",
            error_code="WARN_LATENCY_SPIKE",
            message="P95 latency exceeded threshold: 4200ms > 500ms target SLA",
            trace_id="tr-pay-98126c",
        ),
        # Scenario B logs: redis-cache
        IncidentLog(
            service_name="redis-cache",
            severity="CRITICAL",
            error_code="ERR_REDIS_OOM_EVICTION",
            message="OOM command not allowed when used memory > 'maxmemory' (4090MB / 4096MB)",
            trace_id="tr-red-11029a",
        ),
        IncidentLog(
            service_name="redis-cache",
            severity="ERROR",
            error_code="ERR_REDIS_OOM_EVICTION",
            message="Aggressive eviction cycle started; 2450 volatile keys evicted in last 60s",
            trace_id="tr-red-11030b",
        ),
        # Scenario C logs: auth-service
        IncidentLog(
            service_name="auth-service",
            severity="WARN",
            error_code="WARN_HIGH_CPU_THROTTLING",
            message="Container CPU quota throttled at 96.5% for >180s. Recommend scaling replicas.",
            trace_id="tr-auth-33109a",
        ),
        IncidentLog(
            service_name="auth-service",
            severity="ERROR",
            error_code="WARN_HIGH_CPU_THROTTLING",
            message="JWT verification thread pool saturated, queue depth 42",
            trace_id="tr-auth-33110b",
        ),
        # Downstream symptom log in nginx-ingress
        IncidentLog(
            service_name="nginx-ingress",
            severity="ERROR",
            error_code="HTTP_502_BAD_GATEWAY",
            message=(
                "upstream prematurely closed connection while reading "
                "response header from upstream: payment-api:8080"
            ),
            trace_id="tr-ngx-55102a",
        ),
    ]

    existing_rows = await session.execute(select(IncidentLog.trace_id))
    existing_traces = {row[0] for row in existing_rows.all() if row[0] is not None}

    for log in logs_data:
        if log.trace_id not in existing_traces:
            session.add(log)

    await session.flush()


async def reset_database() -> None:
    """Reset and re-seed operational tables cleanly."""
    await init_db()

    async with session_scope() as session:
        # Delete in reverse foreign-key dependency order
        await session.execute(delete(RemediationExecution))
        await session.execute(delete(IncidentLog))
        await session.execute(delete(InfraService))
        await session.flush()

        await seed_services(session)
        await seed_incident_logs(session)

    logger.info("Operational database reset and re-seeded successfully.")


async def seed_database() -> None:
    """Ensure database tables exist and are populated idempotently."""
    await init_db()

    async with session_scope() as session:
        await seed_services(session)
        await seed_incident_logs(session)

    logger.info("Operational database seeded successfully.")


async def main(reset: bool = False) -> None:
    """Main CLI entrypoint."""
    try:
        if reset:
            await reset_database()
        else:
            await seed_database()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed OmniOps operational database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe existing operational records before seeding.",
    )
    cli_args = parser.parse_args()
    asyncio.run(main(reset=cli_args.reset))
