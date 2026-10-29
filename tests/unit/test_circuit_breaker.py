"""Unit tests for RunbookCircuitBreaker and RunbookClient."""

import json
from pathlib import Path

import httpx
import pytest

from src.mcp_server.runbook_client import (
    CircuitBreakerState,
    RunbookCircuitBreaker,
    RunbookClient,
)

# ---------------------------------------------------------------------------
# Circuit Breaker State Machine Tests
# ---------------------------------------------------------------------------


def get_state(cb: RunbookCircuitBreaker) -> CircuitBreakerState:
    """Helper to prevent mypy attribute narrowing across mutating method calls."""
    return cb.state


def test_circuit_breaker_initial_state() -> None:
    """Verify initial state is CLOSED and can_execute is True."""
    cb = RunbookCircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30.0)
    assert get_state(cb) == CircuitBreakerState.CLOSED
    assert cb.failure_count == 0
    assert cb.can_execute() is True


def test_circuit_breaker_trips_to_open_after_threshold() -> None:
    """Verify breaker transitions to OPEN after failure_threshold failures."""
    cb = RunbookCircuitBreaker(failure_threshold=3)
    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.CLOSED
    assert cb.failure_count == 1
    assert cb.can_execute() is True

    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.CLOSED
    assert cb.failure_count == 2
    assert cb.can_execute() is True

    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.OPEN
    assert cb.failure_count == 3
    assert cb.can_execute() is False


def test_circuit_breaker_cooldown_to_half_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify breaker transitions from OPEN to HALF_OPEN after recovery timeout."""
    cb = RunbookCircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10.0)
    cb.record_failure()
    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.OPEN
    assert cb.can_execute() is False

    # Simulate 5 seconds passing (before cooldown)
    current_time = cb.last_failure_time + 5.0
    monkeypatch.setattr("time.monotonic", lambda: current_time)
    assert cb.can_execute() is False
    assert get_state(cb) == CircuitBreakerState.OPEN

    # Simulate 11 seconds passing (after cooldown)
    current_time = cb.last_failure_time + 11.0
    monkeypatch.setattr("time.monotonic", lambda: current_time)
    assert cb.can_execute() is True
    assert get_state(cb) == CircuitBreakerState.HALF_OPEN


def test_circuit_breaker_half_open_success_resets_to_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify probe success in HALF_OPEN resets state to CLOSED."""
    cb = RunbookCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5.0)
    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.OPEN

    # Transition to HALF_OPEN
    monkeypatch.setattr("time.monotonic", lambda: cb.last_failure_time + 6.0)
    assert cb.can_execute() is True
    assert get_state(cb) == CircuitBreakerState.HALF_OPEN

    # Probe succeeds
    cb.record_success()
    assert get_state(cb) == CircuitBreakerState.CLOSED
    assert cb.failure_count == 0


def test_circuit_breaker_half_open_failure_reopens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify probe failure in HALF_OPEN immediately returns state to OPEN."""
    cb = RunbookCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5.0)
    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.OPEN

    # Transition to HALF_OPEN
    monkeypatch.setattr("time.monotonic", lambda: cb.last_failure_time + 6.0)
    assert cb.can_execute() is True
    assert get_state(cb) == CircuitBreakerState.HALF_OPEN

    # Probe fails
    cb.record_failure()
    assert get_state(cb) == CircuitBreakerState.OPEN


# ---------------------------------------------------------------------------
# RunbookClient Live & Fallback Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runbook_client_live_success() -> None:
    """Verify client returns LIVE_OMNIDOC_RAG when Project 1 responds 200 OK."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert "query" in data
        response_payload = {
            "status": "success",
            "results": [
                {
                    "runbook_id": "RB-104",
                    "title": "Resolving Database Connection Pool Exhaustion",
                    "content": "Increase db_pool_size to 200.",
                    "relevance_score": 0.94,
                }
            ],
        }
        return httpx.Response(200, json=response_payload)

    mock_transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        runbook_client = RunbookClient(
            rag_url="http://mock-rag/api/v1/query",
            client=client,
        )
        output = await runbook_client.search("ERR_DB_POOL_EXHAUSTED")

        assert output.status == "success"
        assert output.source_mode == "LIVE_OMNIDOC_RAG"
        assert len(output.results) == 1
        assert output.results[0].runbook_id == "RB-104"
        assert output.results[0].relevance_score == 0.94
        assert runbook_client.circuit_breaker.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_runbook_client_timeout_falls_back() -> None:
    """Verify client falls back to LOCAL_FALLBACK on timeout."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Mocked request timeout exceeded 1.5s")

    mock_transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        runbook_client = RunbookClient(
            rag_url="http://mock-rag/api/v1/query",
            client=client,
        )
        output = await runbook_client.search("ERR_DB_POOL_EXHAUSTED")

        assert output.status == "success"
        assert output.source_mode == "LOCAL_FALLBACK"
        assert len(output.results) > 0
        assert output.results[0].runbook_id == "RB-104"
        assert runbook_client.circuit_breaker.failure_count == 1


@pytest.mark.asyncio
async def test_runbook_client_connection_error_falls_back() -> None:
    """Verify client falls back to LOCAL_FALLBACK when OmniDoc RAG is offline."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused on port 8080")

    mock_transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        runbook_client = RunbookClient(
            rag_url="http://mock-rag/api/v1/query",
            client=client,
        )
        output = await runbook_client.search("ERR_REDIS_OOM_EVICTION")

        assert output.status == "success"
        assert output.source_mode == "LOCAL_FALLBACK"
        assert len(output.results) > 0
        assert output.results[0].runbook_id == "RB-102"


@pytest.mark.asyncio
async def test_runbook_client_skips_http_when_circuit_open() -> None:
    """Verify that when circuit is OPEN, no HTTP request is attempted."""
    called = False

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"results": []})

    mock_transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        cb = RunbookCircuitBreaker(failure_threshold=1)
        cb.record_failure()  # Trips to OPEN immediately
        assert cb.state == CircuitBreakerState.OPEN

        runbook_client = RunbookClient(
            rag_url="http://mock-rag/api/v1/query",
            circuit_breaker=cb,
            client=client,
        )
        output = await runbook_client.search("HTTP_502_BAD_GATEWAY")

        assert called is False  # Fast-failed without calling HTTP
        assert output.source_mode == "LOCAL_FALLBACK"
        assert output.results[0].runbook_id == "RB-103"


# ---------------------------------------------------------------------------
# Local Fallback Scoring & Bilingual Matching Tests
# ---------------------------------------------------------------------------


def test_local_fallback_scoring_incident_scenarios() -> None:
    """Test accurate identification of all major SRE incident error codes."""
    client = RunbookClient()

    # Scenario A: Payment API pool exhaustion
    res_a = client.search_fallback("ERR_DB_POOL_EXHAUSTED payment-api pool")
    assert len(res_a) > 0
    assert res_a[0].runbook_id == "RB-104"
    assert res_a[0].relevance_score >= 0.75

    # Scenario B: Redis OOM eviction
    res_b = client.search_fallback("ERR_REDIS_OOM_EVICTION redis-cache memory")
    assert len(res_b) > 0
    assert res_b[0].runbook_id == "RB-102"
    assert res_b[0].relevance_score >= 0.75

    # Scenario C: CPU throttling in auth-service
    res_c = client.search_fallback("WARN_HIGH_CPU_THROTTLING auth-service")
    assert len(res_c) > 0
    assert res_c[0].runbook_id == "RB-101"
    assert res_c[0].relevance_score >= 0.75

    # Ingress 502
    res_d = client.search_fallback("HTTP_502_BAD_GATEWAY nginx-ingress")
    assert len(res_d) > 0
    assert res_d[0].runbook_id == "RB-103"
    assert res_d[0].relevance_score >= 0.75


def test_local_fallback_category_filter() -> None:
    """Test category filter strictly limits candidates."""
    client = RunbookClient()

    # Search with category='caching'
    results = client.search_fallback(
        query="memory exhaustion and limit",
        category="caching",
    )
    assert len(results) > 0
    assert results[0].runbook_id == "RB-102"


def test_local_fallback_bilingual_search() -> None:
    """Test searching with Persian phrases matches corresponding runbooks."""
    client = RunbookClient()

    # Persian query for database connection pool
    results = client.search_fallback(query="استخر اتصالات پایگاه داده")
    assert len(results) > 0
    assert results[0].runbook_id == "RB-104"

    # Persian query for CPU throttling
    results_cpu = client.search_fallback(query="مصرف بالای پردازنده رپلیکا")
    assert len(results_cpu) > 0
    assert results_cpu[0].runbook_id == "RB-101"


def test_local_fallback_missing_file_handled(tmp_path: Path) -> None:
    """Test client handles missing fallback file gracefully without raising."""
    non_existent = tmp_path / "does_not_exist.json"
    client = RunbookClient(fallback_path=non_existent)
    results = client.search_fallback("ERR_DB_POOL_EXHAUSTED")
    assert results == []
