"""Unit and functional tests for MCP diagnostic tools."""

import pytest

from src.db.seed import seed_database
from src.db.session import init_db
from src.mcp_server.schemas import KNOWN_SERVICES
from src.mcp_server.tools import (
    _wrap_untrusted_log,
    get_service_health,
    query_incident_logs,
    search_runbooks,
)


@pytest.fixture(autouse=True)
async def setup_test_db() -> None:
    """Ensure database schema is initialized and operational seed data is populated."""
    await init_db()
    await seed_database()


# ---------------------------------------------------------------------------
# Tests: get_service_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_service_health_existing_service() -> None:
    """Verify get_service_health retrieves live metrics for seeded service."""
    res = await get_service_health("payment-api")
    assert res["status"] == "success"
    svc = res["service"]
    assert svc["service_name"] == "payment-api"
    assert svc["health_status"] == "DEGRADED"
    assert svc["db_pool_size"] == 100
    assert svc["active_connections"] == 100
    assert svc["p95_latency_ms"] == 4200
    assert svc["cpu_usage_pct"] > 0


@pytest.mark.asyncio
async def test_get_service_health_redis_cache() -> None:
    """Verify get_service_health retrieves metrics for redis-cache."""
    res = await get_service_health("redis-cache")
    assert res["status"] == "success"
    svc = res["service"]
    assert svc["service_name"] == "redis-cache"
    assert svc["health_status"] == "CRITICAL"
    assert svc["memory_usage_mb"] == 4090
    assert svc["memory_limit_mb"] == 4096


@pytest.mark.asyncio
async def test_get_service_health_unknown_service() -> None:
    """Verify get_service_health returns structured error on hallucinated service name."""
    res = await get_service_health("payment-service")
    assert res["status"] == "error"
    assert res["error_code"] == "SERVICE_NOT_FOUND"
    assert "not found in infrastructure registry" in res["message"]
    assert res["valid_services"] == list(KNOWN_SERVICES)


@pytest.mark.asyncio
async def test_get_service_health_validation_error() -> None:
    """Verify get_service_health handles empty string with structured error."""
    res = await get_service_health("")
    assert res["status"] == "error"
    assert res["error_code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Tests: query_incident_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_incident_logs_existing_service() -> None:
    """Verify query_incident_logs retrieves logs and wraps messages in untrusted tags."""
    res = await query_incident_logs(service_name="payment-api", severity="ERROR", limit=5)
    assert res["status"] == "success"
    assert res["service_name"] == "payment-api"
    assert len(res["logs"]) > 0
    assert res["total_found"] == len(res["logs"])

    # Check untrusted tag encapsulation
    for log in res["logs"]:
        assert log["service_name"] == "payment-api"
        assert log["message"].startswith("<untrusted_log_data>")
        assert log["message"].endswith("</untrusted_log_data>")
        assert "ERR_DB_POOL_EXHAUSTED" in [log["error_code"] for log in res["logs"]]


@pytest.mark.asyncio
async def test_query_incident_logs_severity_threshold() -> None:
    """Verify severity threshold filtering: ERROR includes ERROR and CRITICAL."""
    # payment-api has WARN, ERROR, and CRITICAL logs seeded
    res_critical = await query_incident_logs(
        service_name="payment-api", severity="CRITICAL", limit=10
    )
    assert res_critical["status"] == "success"
    for log in res_critical["logs"]:
        assert log["severity"] == "CRITICAL"

    # CRITICAL should have fewer or equal logs than ERROR
    res_error = await query_incident_logs(service_name="payment-api", severity="ERROR", limit=10)
    assert res_error["status"] == "success"
    assert len(res_error["logs"]) >= len(res_critical["logs"])
    assert any(log["severity"] == "CRITICAL" for log in res_error["logs"])
    assert any(log["severity"] == "ERROR" for log in res_error["logs"])
    assert not any(log["severity"] == "WARN" for log in res_error["logs"])


@pytest.mark.asyncio
async def test_query_incident_logs_limit() -> None:
    """Verify query_incident_logs respects limit parameter."""
    res = await query_incident_logs(service_name="payment-api", limit=1)
    assert res["status"] == "success"
    assert len(res["logs"]) <= 1


@pytest.mark.asyncio
async def test_query_incident_logs_unknown_service() -> None:
    """Verify query_incident_logs returns structured error when service does not exist."""
    res = await query_incident_logs(service_name="auth-api")
    assert res["status"] == "error"
    assert res["error_code"] == "SERVICE_NOT_FOUND"
    assert res["valid_services"] == list(KNOWN_SERVICES)


@pytest.mark.asyncio
async def test_query_incident_logs_validation_error() -> None:
    """Verify query_incident_logs handles invalid limit bounds gracefully."""
    res_zero = await query_incident_logs(service_name="payment-api", limit=0)
    assert res_zero["status"] == "error"
    assert res_zero["error_code"] == "VALIDATION_ERROR"

    res_overflow = await query_incident_logs(service_name="payment-api", limit=50)
    assert res_overflow["status"] == "error"
    assert res_overflow["error_code"] == "VALIDATION_ERROR"


def test_wrap_untrusted_log_idempotent() -> None:
    """Verify _wrap_untrusted_log does not double-wrap already enclosed text."""
    raw = "Unauthorized access attempt"
    wrapped = _wrap_untrusted_log(raw)
    assert wrapped == f"<untrusted_log_data>{raw}</untrusted_log_data>"

    # Second pass should return identical string
    assert _wrap_untrusted_log(wrapped) == wrapped


# ---------------------------------------------------------------------------
# Tests: search_runbooks tool function
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_runbooks_tool_success() -> None:
    """Verify search_runbooks tool returns valid serialized response dictionary."""
    res = await search_runbooks(query="ERR_DB_POOL_EXHAUSTED", category="database")
    assert res["status"] == "success"
    assert res["source_mode"] in ("LIVE_OMNIDOC_RAG", "LOCAL_FALLBACK")
    assert len(res["results"]) > 0
    assert res["results"][0]["runbook_id"] == "RB-104"


@pytest.mark.asyncio
async def test_search_runbooks_tool_validation_error() -> None:
    """Verify search_runbooks tool returns structured error on empty query."""
    res = await search_runbooks(query="")
    assert res["status"] == "error"
    assert res["error_code"] == "VALIDATION_ERROR"
