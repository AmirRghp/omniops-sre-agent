"""Pydantic V2 input and output schemas for OmniOps SRE Agent MCP tools.

Defines strict type-safe models for all 4 MCP tools:
- search_runbooks
- query_incident_logs
- get_service_health
- execute_remediation
and the structured self-healing error model ToolErrorResponse.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Common Constants and Enumerated Types
# ---------------------------------------------------------------------------

KNOWN_SERVICES: tuple[str, ...] = (
    "payment-api",
    "auth-service",
    "postgres-primary",
    "redis-cache",
    "nginx-ingress",
)

RunbookCategory = Literal["database", "networking", "containers", "caching", "general"]
LogSeverity = Literal["WARN", "ERROR", "CRITICAL"]
ServiceStatus = Literal["HEALTHY", "DEGRADED", "CRITICAL", "RESTARTING"]
RemediationActionType = Literal[
    "restart_service",
    "scale_replicas",
    "flush_redis_cache",
    "increase_db_pool",
]
SourceMode = Literal["LIVE_OMNIDOC_RAG", "LOCAL_FALLBACK"]


# ---------------------------------------------------------------------------
# Structured Self-Correction Tool Error Contract
# ---------------------------------------------------------------------------


class ToolErrorResponse(BaseModel):
    """Structured error contract returned instead of raising unhandled exceptions to LLM."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = Field(
        default="error",
        description="Error status indicator.",
    )
    error_code: str = Field(
        default="SERVICE_NOT_FOUND",
        description="Machine-readable error code.",
    )
    message: str = Field(
        ...,
        description="Descriptive explanation of the error.",
    )
    valid_services: list[str] = Field(
        default_factory=lambda: list(KNOWN_SERVICES),
        description="List of valid service identifiers known to the registry.",
    )


# ---------------------------------------------------------------------------
# Tool 1: search_runbooks
# ---------------------------------------------------------------------------


class SearchRunbooksInput(BaseModel):
    """Input parameters for searching troubleshooting runbooks."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        ...,
        description=(
            "Technical error code, symptom, or infrastructure keyword "
            "(e.g., 'ERR_DB_POOL_EXHAUSTED' or 'Nginx 502 Bad Gateway')."
        ),
        min_length=1,
    )
    category: RunbookCategory | None = Field(
        default=None,
        description="Optional infrastructure domain filter.",
    )


class RunbookResult(BaseModel):
    """Individual matching runbook snippet and relevance score."""

    model_config = ConfigDict(extra="forbid")

    runbook_id: str = Field(
        ...,
        description="Identifier of the runbook (e.g., 'RB-104').",
    )
    title: str = Field(
        ...,
        description="Title of the runbook.",
    )
    content: str = Field(
        ...,
        description="Actionable runbook guidance and remediation steps.",
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity or ranking score between 0.0 and 1.0.",
    )


class SearchRunbooksOutput(BaseModel):
    """Output payload returned by search_runbooks."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"] = Field(
        default="success",
        description="Execution status.",
    )
    source_mode: SourceMode = Field(
        ...,
        description="Source used for retrieval: LIVE_OMNIDOC_RAG or LOCAL_FALLBACK.",
    )
    results: list[RunbookResult] = Field(
        default_factory=list,
        description="List of matching runbooks.",
    )


# ---------------------------------------------------------------------------
# Tool 2: query_incident_logs
# ---------------------------------------------------------------------------


class QueryIncidentLogsInput(BaseModel):
    """Input parameters for querying operational incident logs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_name: str = Field(
        ...,
        description=(
            "Exact microservice identifier (e.g., 'payment-api', 'auth-service', "
            "'redis-cache', 'postgres-primary', 'nginx-ingress')."
        ),
        min_length=1,
    )
    severity: LogSeverity = Field(
        default="ERROR",
        description="Severity threshold filter.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of logs to return (1-20).",
    )


class IncidentLogItem(BaseModel):
    """Structured operational log item."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | str = Field(
        ...,
        description="Unique log record identifier.",
    )
    service_name: str = Field(
        ...,
        description="Originating service identifier.",
    )
    severity: str = Field(
        ...,
        description="Severity level (INFO, WARN, ERROR, CRITICAL).",
    )
    error_code: str = Field(
        ...,
        description="Categorized error or event code.",
    )
    message: str = Field(
        ...,
        description="Log message text wrapped in untrusted data delimiters.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Distributed tracing identifier.",
    )
    created_at: datetime | None = Field(
        default=None,
        description="Timestamp when the event occurred.",
    )


class QueryIncidentLogsOutput(BaseModel):
    """Output payload returned by query_incident_logs."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"] = Field(
        default="success",
        description="Execution status.",
    )
    service_name: str = Field(
        ...,
        description="Queried microservice name.",
    )
    logs: list[IncidentLogItem] = Field(
        default_factory=list,
        description="Retrieved log entries.",
    )
    total_found: int = Field(
        default=0,
        ge=0,
        description="Total number of matched logs.",
    )


# ---------------------------------------------------------------------------
# Tool 3: get_service_health
# ---------------------------------------------------------------------------


class GetServiceHealthInput(BaseModel):
    """Input parameters for inspecting service health and telemetry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_name: str = Field(
        ...,
        description="Exact microservice identifier.",
        min_length=1,
    )


class ServiceHealthDetails(BaseModel):
    """Live resource utilization and state metrics for a microservice."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(
        ...,
        description="Exact microservice identifier.",
    )
    health_status: ServiceStatus = Field(
        ...,
        description="Operational status of the service.",
    )
    cpu_usage_pct: float = Field(
        ...,
        ge=0.0,
        description="CPU utilization percentage.",
    )
    memory_usage_mb: int = Field(
        ...,
        ge=0,
        description="Memory usage in megabytes.",
    )
    memory_limit_mb: int = Field(
        ...,
        ge=1,
        description="Memory limit in megabytes.",
    )
    p95_latency_ms: int = Field(
        ...,
        ge=0,
        description="95th percentile response latency in milliseconds.",
    )
    active_replicas: int = Field(
        ...,
        ge=0,
        description="Number of healthy running replicas.",
    )
    max_replicas: int = Field(
        ...,
        ge=1,
        description="Maximum replica autoscaling ceiling.",
    )
    db_pool_size: int = Field(
        default=100,
        ge=1,
        description="Database connection pool size limit.",
    )
    active_connections: int = Field(
        default=20,
        ge=0,
        description="Currently active open database connections.",
    )


class GetServiceHealthOutput(BaseModel):
    """Output payload returned by get_service_health."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"] = Field(
        default="success",
        description="Execution status.",
    )
    service: ServiceHealthDetails = Field(
        ...,
        description="Current health and capacity metrics.",
    )


# ---------------------------------------------------------------------------
# Tool 4: execute_remediation
# ---------------------------------------------------------------------------


class ExecuteRemediationInput(BaseModel):
    """Input parameters for applying state-changing remediation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_name: str = Field(
        ...,
        description="Target microservice name.",
        min_length=1,
    )
    action_type: RemediationActionType = Field(
        ...,
        description="Specific remediation operation to perform.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action parameters (e.g., {'pool_size': 200} or {'replicas': 4}).",
    )
    idempotency_key: str = Field(
        ...,
        description="Unique deterministic key for this action.",
        min_length=1,
    )
    reason: str = Field(
        ...,
        description="Evidence-based explanation citing the log error code and runbook ID.",
        min_length=1,
    )


class ExecuteRemediationOutput(BaseModel):
    """Output payload returned by execute_remediation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"] = Field(
        default="success",
        description="Execution outcome status.",
    )
    action_type: str = Field(
        ...,
        description="Remediation operation performed.",
    )
    service_name: str = Field(
        ...,
        description="Target microservice name.",
    )
    idempotency_key: str = Field(
        ...,
        description="Idempotency key associated with this action.",
    )
    idempotent_replay: bool = Field(
        default=False,
        description="True if result was returned from prior execution cache.",
    )
    message: str = Field(
        ...,
        description="Summary of the action outcome.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Updated metrics or execution details.",
    )
    executed_at: datetime | None = Field(
        default=None,
        description="Timestamp when remediation was executed.",
    )
