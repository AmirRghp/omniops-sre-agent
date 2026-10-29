"""Unit tests for MCP Pydantic V2 tool input and output schemas."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.mcp_server.schemas import (
    KNOWN_SERVICES,
    ExecuteRemediationInput,
    ExecuteRemediationOutput,
    GetServiceHealthInput,
    GetServiceHealthOutput,
    IncidentLogItem,
    QueryIncidentLogsInput,
    QueryIncidentLogsOutput,
    RunbookResult,
    SearchRunbooksInput,
    SearchRunbooksOutput,
    ServiceHealthDetails,
    ToolErrorResponse,
)

# ---------------------------------------------------------------------------
# Tests: ToolErrorResponse
# ---------------------------------------------------------------------------


def test_tool_error_response_defaults() -> None:
    """Test ToolErrorResponse defaults to SERVICE_NOT_FOUND and lists KNOWN_SERVICES."""
    err = ToolErrorResponse(message="Service 'billing' not recognized.")
    assert err.status == "error"
    assert err.error_code == "SERVICE_NOT_FOUND"
    assert err.message == "Service 'billing' not recognized."
    assert err.valid_services == list(KNOWN_SERVICES)


def test_tool_error_response_custom_fields() -> None:
    """Test ToolErrorResponse with custom error code and valid_services list."""
    err = ToolErrorResponse(
        error_code="INVALID_PARAMETER",
        message="Invalid pool size",
        valid_services=["payment-api"],
    )
    assert err.error_code == "INVALID_PARAMETER"
    assert err.valid_services == ["payment-api"]


def test_tool_error_response_forbids_extra_fields() -> None:
    """Test ToolErrorResponse rejects unknown fields."""
    with pytest.raises(ValidationError):
        ToolErrorResponse(message="Error", extra_field="forbidden")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Tests: search_runbooks schemas
# ---------------------------------------------------------------------------


def test_search_runbooks_input_valid() -> None:
    """Test valid SearchRunbooksInput parsing and whitespace stripping."""
    inp = SearchRunbooksInput(query="  ERR_DB_POOL_EXHAUSTED  ", category="database")
    assert inp.query == "ERR_DB_POOL_EXHAUSTED"
    assert inp.category == "database"


def test_search_runbooks_input_optional_category() -> None:
    """Test SearchRunbooksInput without category defaults to None."""
    inp = SearchRunbooksInput(query="Nginx 502")
    assert inp.query == "Nginx 502"
    assert inp.category is None


def test_search_runbooks_input_invalid_category() -> None:
    """Test SearchRunbooksInput rejects unsupported categories."""
    with pytest.raises(ValidationError):
        SearchRunbooksInput(query="test", category="unknown_category")  # type: ignore[arg-type]


def test_search_runbooks_input_empty_query() -> None:
    """Test SearchRunbooksInput rejects empty query string."""
    with pytest.raises(ValidationError):
        SearchRunbooksInput(query="")


def test_search_runbooks_output_roundtrip() -> None:
    """Test SearchRunbooksOutput model serialization and deserialization."""
    res = RunbookResult(
        runbook_id="RB-104",
        title="Resolving Database Connection Pool Exhaustion",
        content="Increase db_pool_size to 200.",
        relevance_score=0.94,
    )
    out = SearchRunbooksOutput(
        status="success",
        source_mode="LIVE_OMNIDOC_RAG",
        results=[res],
    )
    dumped = out.model_dump()
    assert dumped["status"] == "success"
    assert dumped["source_mode"] == "LIVE_OMNIDOC_RAG"
    assert len(dumped["results"]) == 1
    assert dumped["results"][0]["runbook_id"] == "RB-104"

    # Re-validate from dict
    restored = SearchRunbooksOutput.model_validate(dumped)
    assert restored == out


def test_runbook_result_score_bounds() -> None:
    """Test relevance_score must be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        RunbookResult(
            runbook_id="RB-1",
            title="T",
            content="C",
            relevance_score=1.5,
        )
    with pytest.raises(ValidationError):
        RunbookResult(
            runbook_id="RB-1",
            title="T",
            content="C",
            relevance_score=-0.1,
        )


# ---------------------------------------------------------------------------
# Tests: query_incident_logs schemas
# ---------------------------------------------------------------------------


def test_query_incident_logs_input_defaults() -> None:
    """Test QueryIncidentLogsInput default severity and limit."""
    inp = QueryIncidentLogsInput(service_name="payment-api")
    assert inp.service_name == "payment-api"
    assert inp.severity == "ERROR"
    assert inp.limit == 5


def test_query_incident_logs_input_custom_bounds() -> None:
    """Test QueryIncidentLogsInput custom limit and valid severity."""
    inp = QueryIncidentLogsInput(
        service_name="redis-cache",
        severity="CRITICAL",
        limit=20,
    )
    assert inp.limit == 20
    assert inp.severity == "CRITICAL"


def test_query_incident_logs_input_limit_out_of_bounds() -> None:
    """Test limit < 1 or limit > 20 raises ValidationError."""
    with pytest.raises(ValidationError):
        QueryIncidentLogsInput(service_name="payment-api", limit=0)

    with pytest.raises(ValidationError):
        QueryIncidentLogsInput(service_name="payment-api", limit=21)


def test_query_incident_logs_input_invalid_severity() -> None:
    """Test unsupported severity raises ValidationError."""
    with pytest.raises(ValidationError):
        QueryIncidentLogsInput(service_name="payment-api", severity="DEBUG")  # type: ignore[arg-type]


def test_query_incident_logs_output_roundtrip() -> None:
    """Test QueryIncidentLogsOutput serialization with IncidentLogItem."""
    log_id = uuid.uuid4()
    now = datetime.now(UTC)
    item = IncidentLogItem(
        id=log_id,
        service_name="payment-api",
        severity="ERROR",
        error_code="ERR_DB_POOL_EXHAUSTED",
        message="<untrusted_log_data>QueuePool limit reached</untrusted_log_data>",
        trace_id="tr-12345",
        created_at=now,
    )
    out = QueryIncidentLogsOutput(
        status="success",
        service_name="payment-api",
        logs=[item],
        total_found=1,
    )
    dumped = out.model_dump()
    assert dumped["status"] == "success"
    assert dumped["total_found"] == 1
    assert dumped["logs"][0]["error_code"] == "ERR_DB_POOL_EXHAUSTED"


# ---------------------------------------------------------------------------
# Tests: get_service_health schemas
# ---------------------------------------------------------------------------


def test_get_service_health_input_valid() -> None:
    """Test GetServiceHealthInput validates service_name."""
    inp = GetServiceHealthInput(service_name="payment-api")
    assert inp.service_name == "payment-api"


def test_get_service_health_input_empty_name() -> None:
    """Test GetServiceHealthInput rejects empty string."""
    with pytest.raises(ValidationError):
        GetServiceHealthInput(service_name="")


def test_get_service_health_output_roundtrip() -> None:
    """Test GetServiceHealthOutput validates and dumps full service health details."""
    details = ServiceHealthDetails(
        service_name="payment-api",
        health_status="DEGRADED",
        cpu_usage_pct=34.5,
        memory_usage_mb=1024,
        memory_limit_mb=2048,
        p95_latency_ms=4200,
        active_replicas=3,
        max_replicas=6,
        db_pool_size=100,
        active_connections=100,
    )
    out = GetServiceHealthOutput(status="success", service=details)
    dumped = out.model_dump()
    assert dumped["service"]["health_status"] == "DEGRADED"
    assert dumped["service"]["cpu_usage_pct"] == 34.5
    assert dumped["service"]["p95_latency_ms"] == 4200


def test_service_health_details_invalid_status() -> None:
    """Test ServiceHealthDetails rejects unknown health_status."""
    with pytest.raises(ValidationError):
        ServiceHealthDetails(
            service_name="payment-api",
            health_status="UNKNOWN",  # type: ignore[arg-type]
            cpu_usage_pct=10.0,
            memory_usage_mb=100,
            memory_limit_mb=200,
            p95_latency_ms=50,
            active_replicas=1,
            max_replicas=2,
        )


# ---------------------------------------------------------------------------
# Tests: execute_remediation schemas
# ---------------------------------------------------------------------------


def test_execute_remediation_input_valid() -> None:
    """Test ExecuteRemediationInput parsing and validation."""
    inp = ExecuteRemediationInput(
        service_name="payment-api",
        action_type="increase_db_pool",
        parameters={"pool_size": 200},
        idempotency_key="idem_payment_api_increase_pool_200",
        reason="ERR_DB_POOL_EXHAUSTED observed in logs. RB-104 advises increasing pool to 200.",
    )
    assert inp.action_type == "increase_db_pool"
    assert inp.parameters == {"pool_size": 200}
    assert inp.idempotency_key == "idem_payment_api_increase_pool_200"


def test_execute_remediation_input_invalid_action() -> None:
    """Test ExecuteRemediationInput rejects unsupported action_type."""
    with pytest.raises(ValidationError):
        ExecuteRemediationInput(
            service_name="payment-api",
            action_type="drop_database",  # type: ignore[arg-type]
            idempotency_key="key-1",
            reason="testing",
        )


def test_execute_remediation_output_roundtrip() -> None:
    """Test ExecuteRemediationOutput serialization."""
    out = ExecuteRemediationOutput(
        status="success",
        action_type="increase_db_pool",
        service_name="payment-api",
        idempotency_key="idem_payment_api_increase_pool_200",
        idempotent_replay=False,
        message="Database connection pool size increased to 200.",
        details={"previous_pool_size": 100, "new_pool_size": 200},
        executed_at=datetime.now(UTC),
    )
    dumped = out.model_dump()
    assert dumped["status"] == "success"
    assert dumped["idempotent_replay"] is False
    assert dumped["details"]["new_pool_size"] == 200
