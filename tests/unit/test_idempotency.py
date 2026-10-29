"""Unit tests for the idempotent execute_remediation MCP tool."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select

from src.db.models import InfraService, RemediationExecution
from src.db.seed import reset_database
from src.db.session import session_scope
from src.mcp_server.schemas import KNOWN_SERVICES
from src.mcp_server.tools import execute_remediation

REASON = "ERR_DB_POOL_EXHAUSTED observed in logs; RB-104 recommends increasing the pool."


@pytest.fixture(autouse=True)
async def reset_state() -> None:
    """Reset operational tables before each test for deterministic state."""
    await reset_database()


async def _service_snapshot(service_name: str) -> dict[str, Any]:
    """Read the persisted state of a service after a tool call."""
    async with session_scope() as session:
        service = await session.get(InfraService, service_name)
        assert service is not None
        return {
            "status": service.status,
            "db_pool_size": service.db_pool_size,
            "p95_latency_ms": service.p95_latency_ms,
            "active_replicas": service.active_replicas,
            "memory_usage_mb": service.memory_usage_mb,
        }


async def _audit_snapshots() -> list[dict[str, Any]]:
    """Read remediation audit rows for assertions."""
    async with session_scope() as session:
        result = await session.execute(
            select(RemediationExecution).order_by(RemediationExecution.created_at)
        )
        return [
            {
                "idempotency_key": record.idempotency_key,
                "thread_id": record.thread_id,
                "approved_by": record.approved_by,
                "approval_status": record.approval_status,
                "executed_at": record.executed_at,
                "execution_result": record.execution_result,
            }
            for record in result.scalars().all()
        ]


async def _audit_count() -> int:
    """Count remediation audit rows."""
    async with session_scope() as session:
        count = (
            await session.execute(select(func.count()).select_from(RemediationExecution))
        ).scalar()
    return count or 0


# ---------------------------------------------------------------------------
# Tests: mutation and audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_applies_mutation_and_audit() -> None:
    """Verify the first execution mutates the service and writes an audit record."""
    result = await execute_remediation(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_payment_pool_200",
        reason=REASON,
        thread_id="inc_test_001",
        approved_by="sre_admin",
    )

    assert result["status"] == "success"
    assert result["service_name"] == "payment-api"
    assert result["idempotent_replay"] is False
    assert result["details"]["previous_pool_size"] == 100
    assert result["details"]["new_pool_size"] == 200
    assert result["executed_at"] is not None

    snapshot = await _service_snapshot("payment-api")
    assert snapshot["status"] == "HEALTHY"
    assert snapshot["db_pool_size"] == 200
    assert snapshot["p95_latency_ms"] == 140

    records = await _audit_snapshots()
    assert len(records) == 1
    record = records[0]
    assert record["idempotency_key"] == "idem_payment_pool_200"
    assert record["thread_id"] == "inc_test_001"
    assert record["approved_by"] == "sre_admin"
    assert record["approval_status"] == "APPROVED"
    assert record["executed_at"] is not None
    assert record["execution_result"]["idempotent_replay"] is False
    assert record["execution_result"]["details"]["new_pool_size"] == 200


@pytest.mark.asyncio
async def test_execute_remediation_replays_cached_result() -> None:
    """Verify a duplicate idempotency key returns the cache without re-mutating."""
    first = await execute_remediation(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_payment_pool_200",
        reason=REASON,
    )
    second = await execute_remediation(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_payment_pool_200",
        reason=REASON,
    )

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert second["details"] == first["details"]
    assert second["executed_at"] == first["executed_at"]

    snapshot = await _service_snapshot("payment-api")
    assert snapshot["db_pool_size"] == 200
    assert snapshot["p95_latency_ms"] == 140

    records = await _audit_snapshots()
    assert len(records) == 1
    assert records[0]["thread_id"] == "mcp-direct"


# ---------------------------------------------------------------------------
# Tests: structured errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_unknown_service_returns_structured_error() -> None:
    """Verify an unknown service returns SERVICE_NOT_FOUND without an audit row."""
    result = await execute_remediation(
        service_name="payment-service",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_unknown_service",
        reason=REASON,
    )

    assert result["status"] == "error"
    assert result["error_code"] == "SERVICE_NOT_FOUND"
    assert result["valid_services"] == list(KNOWN_SERVICES)
    assert await _audit_count() == 0


@pytest.mark.parametrize(
    "parameters",
    [{}, {"pool_size": 0}, {"pool_size": "200"}],
)
@pytest.mark.asyncio
async def test_execute_remediation_invalid_parameters(parameters: dict[str, Any]) -> None:
    """Verify invalid action parameters are rejected before any mutation."""
    result = await execute_remediation(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters=parameters,
        idempotency_key="idem_invalid_pool",
        reason=REASON,
    )

    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_PARAMETERS"

    snapshot = await _service_snapshot("payment-api")
    assert snapshot["status"] == "DEGRADED"
    assert snapshot["db_pool_size"] == 100
    assert await _audit_count() == 0


@pytest.mark.asyncio
async def test_execute_remediation_rejects_key_reuse_for_different_action() -> None:
    """Verify an existing idempotency key cannot be reused for another action."""
    first = await execute_remediation(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_shared_key",
        reason=REASON,
    )
    assert first["status"] == "success"

    conflict = await execute_remediation(
        service_name="payment-api",
        action_type="flush_redis_cache",
        parameters={},
        idempotency_key="idem_shared_key",
        reason="Retrying with a different action must not execute.",
    )

    assert conflict["status"] == "error"
    assert conflict["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert await _audit_count() == 1

    snapshot = await _service_snapshot("payment-api")
    assert snapshot["db_pool_size"] == 200
    assert snapshot["status"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Tests: remaining actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_scale_replicas_updates_capacity() -> None:
    """Verify scale_replicas increases replicas and marks the service healthy."""
    result = await execute_remediation(
        service_name="auth-service",
        action_type="scale_replicas",
        parameters={"replicas": 4},
        idempotency_key="idem_auth_scale_4",
        reason="WARN_HIGH_CPU_THROTTLING; RB-107 recommends scaling to 4 replicas.",
    )

    assert result["status"] == "success"
    assert result["details"]["previous_replicas"] == 2
    assert result["details"]["new_replicas"] == 4

    snapshot = await _service_snapshot("auth-service")
    assert snapshot["active_replicas"] == 4
    assert snapshot["status"] == "HEALTHY"


@pytest.mark.asyncio
async def test_execute_remediation_scale_replicas_above_max_rejected() -> None:
    """Verify replicas beyond max_replicas are rejected without mutation."""
    result = await execute_remediation(
        service_name="auth-service",
        action_type="scale_replicas",
        parameters={"replicas": 99},
        idempotency_key="idem_auth_scale_99",
        reason="Invalid scale target.",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_PARAMETERS"

    snapshot = await _service_snapshot("auth-service")
    assert snapshot["active_replicas"] == 2
    assert snapshot["status"] == "DEGRADED"
    assert await _audit_count() == 0


@pytest.mark.parametrize(
    ("service_name", "action_type", "expected"),
    [
        ("nginx-ingress", "restart_service", {"status": "HEALTHY", "p95_latency_ms": 85}),
        (
            "redis-cache",
            "flush_redis_cache",
            {"status": "HEALTHY", "memory_usage_mb": 512, "p95_latency_ms": 100},
        ),
    ],
)
@pytest.mark.asyncio
async def test_execute_remediation_restart_and_flush_actions(
    service_name: str,
    action_type: str,
    expected: dict[str, Any],
) -> None:
    """Verify restart_service and flush_redis_cache apply their state changes."""
    result = await execute_remediation(
        service_name=service_name,
        action_type=action_type,
        parameters={},
        idempotency_key=f"idem_{service_name}_{action_type}",
        reason="Apply the documented recovery action.",
    )

    assert result["status"] == "success"
    snapshot = await _service_snapshot(service_name)
    for field, value in expected.items():
        assert snapshot[field] == value
    assert await _audit_count() == 1


# ---------------------------------------------------------------------------
# Tests: concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_concurrent_duplicates_apply_once() -> None:
    """Verify racing duplicate calls produce one mutation and one replay."""
    results = await asyncio.gather(
        execute_remediation(
            service_name="payment-api",
            action_type="increase_db_pool",
            parameters={"pool_size": 200},
            idempotency_key="idem_concurrent_pool_200",
            reason=REASON,
        ),
        execute_remediation(
            service_name="payment-api",
            action_type="increase_db_pool",
            parameters={"pool_size": 200},
            idempotency_key="idem_concurrent_pool_200",
            reason=REASON,
        ),
    )

    assert [result["status"] for result in results] == ["success", "success"]
    assert sorted(result["idempotent_replay"] for result in results) == [False, True]

    snapshot = await _service_snapshot("payment-api")
    assert snapshot["db_pool_size"] == 200
    assert snapshot["p95_latency_ms"] == 140
    assert await _audit_count() == 1
