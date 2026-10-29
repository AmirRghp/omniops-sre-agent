"""Model Context Protocol (MCP) tool implementations for OmniOps SRE Agent.

Defines the core diagnostic and research tools:
- get_service_health: Read-only inspection of microservice metrics and state.
- query_incident_logs: Read-only query of operational error logs with prompt injection defense.
- search_runbooks: Read-only runbook search with circuit breaker fallback.
- execute_remediation: HITL-gated, idempotent write tool backed by the audit ledger.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logger import setup_logger
from src.db.models import IncidentLog, InfraService, RemediationExecution
from src.db.session import session_scope
from src.mcp_server.runbook_client import RunbookClient
from src.mcp_server.schemas import (
    KNOWN_SERVICES,
    ExecuteRemediationInput,
    ExecuteRemediationOutput,
    GetServiceHealthInput,
    GetServiceHealthOutput,
    IncidentLogItem,
    QueryIncidentLogsInput,
    QueryIncidentLogsOutput,
    SearchRunbooksInput,
    ServiceHealthDetails,
    ToolErrorResponse,
)

logger = setup_logger("mcp_tools")

# Severity threshold mapping: selecting a severity queries that level and above
SEVERITY_HIERARCHY: dict[str, list[str]] = {
    "WARN": ["WARN", "ERROR", "CRITICAL"],
    "ERROR": ["ERROR", "CRITICAL"],
    "CRITICAL": ["CRITICAL"],
}


@asynccontextmanager
async def _get_session(
    session: AsyncSession | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager yielding the provided session or an auto-scoped session."""
    if session is not None:
        yield session
    else:
        async with session_scope() as s:
            yield s


def _wrap_untrusted_log(message: str) -> str:
    """Enclose log text in <untrusted_log_data> tags to neutralize prompt injection."""
    clean_msg = message.strip()
    if clean_msg.startswith("<untrusted_log_data>") and clean_msg.endswith("</untrusted_log_data>"):
        inner = clean_msg[len("<untrusted_log_data>") : -len("</untrusted_log_data>")]
    else:
        inner = clean_msg
    escaped_inner = inner.replace("<untrusted_log_data>", "&lt;untrusted_log_data&gt;").replace(
        "</untrusted_log_data>", "&lt;/untrusted_log_data&gt;"
    )
    return f"<untrusted_log_data>{escaped_inner}</untrusted_log_data>"


async def get_service_health(
    service_name: str,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Retrieve real-time resource utilization, replica counts, connection pools, and status.

    Returns structured error dict if service does not exist in registry.
    """
    try:
        validated = GetServiceHealthInput(service_name=service_name)
    except ValidationError as err:
        return ToolErrorResponse(
            status="error",
            error_code="VALIDATION_ERROR",
            message=f"Invalid service_name parameter: {err.errors()[0]['msg']}",
            valid_services=list(KNOWN_SERVICES),
        ).model_dump()

    async with _get_session(session) as s:
        stmt = select(InfraService).where(InfraService.service_name == validated.service_name)
        result = await s.execute(stmt)
        service = result.scalar_one_or_none()

    if service is None:
        return ToolErrorResponse(
            status="error",
            error_code="SERVICE_NOT_FOUND",
            message=f"Service '{service_name}' not found in infrastructure registry.",
            valid_services=list(KNOWN_SERVICES),
        ).model_dump()

    details = ServiceHealthDetails(
        service_name=service.service_name,
        health_status=service.status,  # type: ignore[arg-type]
        cpu_usage_pct=float(service.cpu_usage_pct),
        memory_usage_mb=service.memory_usage_mb,
        memory_limit_mb=service.memory_limit_mb,
        p95_latency_ms=service.p95_latency_ms,
        active_replicas=service.active_replicas,
        max_replicas=service.max_replicas,
        db_pool_size=service.db_pool_size,
        active_connections=service.active_connections,
    )
    return GetServiceHealthOutput(status="success", service=details).model_dump()


async def query_incident_logs(
    service_name: str,
    severity: str = "ERROR",
    limit: int = 5,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Fetch recent structured logs for a specific microservice from PostgreSQL.

    Wraps log messages in <untrusted_log_data> tags to counter indirect prompt injection.
    """
    try:
        validated = QueryIncidentLogsInput(
            service_name=service_name,
            severity=severity,  # type: ignore[arg-type]
            limit=limit,
        )
    except ValidationError as err:
        return ToolErrorResponse(
            status="error",
            error_code="VALIDATION_ERROR",
            message=f"Invalid parameters for query_incident_logs: {err.errors()[0]['msg']}",
            valid_services=list(KNOWN_SERVICES),
        ).model_dump()

    async with _get_session(session) as s:
        # Precondition check: verify service existence
        check_stmt = select(InfraService.service_name).where(
            InfraService.service_name == validated.service_name
        )
        check_res = await s.execute(check_stmt)
        if check_res.scalar_one_or_none() is None:
            return ToolErrorResponse(
                status="error",
                error_code="SERVICE_NOT_FOUND",
                message=f"Service '{service_name}' not found in infrastructure registry.",
                valid_services=list(KNOWN_SERVICES),
            ).model_dump()

        # Query logs matching service and severity threshold
        allowed_severities = SEVERITY_HIERARCHY.get(validated.severity, [validated.severity])
        stmt = (
            select(IncidentLog)
            .where(
                IncidentLog.service_name == validated.service_name,
                IncidentLog.severity.in_(allowed_severities),
            )
            .order_by(IncidentLog.created_at.desc())
            .limit(validated.limit)
        )
        result = await s.execute(stmt)
        logs = list(result.scalars().all())

    log_items: list[IncidentLogItem] = []
    for log in logs:
        log_items.append(
            IncidentLogItem(
                id=log.id,
                service_name=log.service_name,
                severity=log.severity,
                error_code=log.error_code,
                message=_wrap_untrusted_log(log.message),
                trace_id=log.trace_id,
                created_at=log.created_at,
            )
        )

    return QueryIncidentLogsOutput(
        status="success",
        service_name=validated.service_name,
        logs=log_items,
        total_found=len(log_items),
    ).model_dump()


async def search_runbooks(
    query: str,
    category: str | None = None,
    client: RunbookClient | None = None,
) -> dict[str, Any]:
    """Search troubleshooting runbooks via OmniDoc RAG or transparent local fallback."""
    try:
        validated = SearchRunbooksInput(
            query=query,
            category=category,  # type: ignore[arg-type]
        )
    except ValidationError as err:
        return ToolErrorResponse(
            status="error",
            error_code="VALIDATION_ERROR",
            message=f"Invalid search parameters: {err.errors()[0]['msg']}",
            valid_services=list(KNOWN_SERVICES),
        ).model_dump()

    runbook_client = client or RunbookClient()
    output = await runbook_client.search(query=validated.query, category=validated.category)
    return output.model_dump()


async def _fetch_execution(
    session: AsyncSession,
    idempotency_key: str,
) -> RemediationExecution | None:
    """Look up a remediation audit record by its unique idempotency key."""
    result = await session.execute(
        select(RemediationExecution).where(RemediationExecution.idempotency_key == idempotency_key)
    )
    record: RemediationExecution | None = result.scalar_one_or_none()
    return record


def _cached_or_conflict(
    record: RemediationExecution,
    request: ExecuteRemediationInput,
) -> dict[str, Any]:
    """Return the cached result for an identical request or a conflict response."""
    if (
        record.approval_status == "APPROVED"
        and record.execution_result is not None
        and record.service_name == request.service_name
        and record.action_type == request.action_type
        and record.parameters == request.parameters
    ):
        cached = ExecuteRemediationOutput.model_validate(record.execution_result)
        cached.idempotent_replay = True
        return cached.model_dump()

    return ToolErrorResponse(
        error_code="IDEMPOTENCY_CONFLICT",
        message=(
            f"Idempotency key '{request.idempotency_key}' was already used for a "
            "different or incomplete remediation."
        ),
        valid_services=list(KNOWN_SERVICES),
    ).model_dump()


def _apply_remediation_mutation(
    service: InfraService,
    action_type: str,
    parameters: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Apply a simulated remediation to the service row.

    Returns execution details and an optional validation error. Parameter validation
    happens before any mutation, so rejected requests leave the row untouched.
    """
    if action_type == "increase_db_pool":
        raw_pool_size = (
            parameters.get("pool_size")
            if "pool_size" in parameters
            else parameters.get("db_pool_size", parameters.get("new_pool_size"))
        )
        if (
            isinstance(raw_pool_size, bool)
            or not isinstance(raw_pool_size, int)
            or not 1 <= raw_pool_size <= 1000
        ):
            return {}, "increase_db_pool requires an integer 'pool_size' between 1 and 1000."

        previous_pool_size = service.db_pool_size
        service.db_pool_size = raw_pool_size
        service.status = "HEALTHY"
        service.p95_latency_ms = min(service.p95_latency_ms, 140)
        return {
            "previous_pool_size": previous_pool_size,
            "new_pool_size": raw_pool_size,
            "status": service.status,
            "p95_latency_ms": service.p95_latency_ms,
        }, None

    if action_type == "scale_replicas":
        raw_replicas = parameters.get("replicas")
        if (
            isinstance(raw_replicas, bool)
            or not isinstance(raw_replicas, int)
            or not 1 <= raw_replicas <= service.max_replicas
        ):
            return (
                {},
                f"scale_replicas requires an integer 'replicas' between 1 and "
                f"{service.max_replicas}.",
            )

        previous_replicas = service.active_replicas
        service.active_replicas = raw_replicas
        service.cpu_usage_pct = min(
            service.cpu_usage_pct * previous_replicas / raw_replicas,
            Decimal("100.00"),
        )
        service.status = "HEALTHY"
        return {
            "previous_replicas": previous_replicas,
            "new_replicas": raw_replicas,
            "cpu_usage_pct": float(service.cpu_usage_pct),
            "status": service.status,
        }, None

    if action_type == "restart_service":
        restarted_at = datetime.now(UTC)
        service.status = "HEALTHY"
        service.last_restarted_at = restarted_at
        service.p95_latency_ms = min(service.p95_latency_ms, 200)
        return {
            "status": service.status,
            "last_restarted_at": restarted_at.isoformat(),
            "p95_latency_ms": service.p95_latency_ms,
        }, None

    if action_type == "flush_redis_cache":
        previous_memory_usage_mb = service.memory_usage_mb
        service.memory_usage_mb = min(512, service.memory_limit_mb)
        service.status = "HEALTHY"
        service.p95_latency_ms = min(service.p95_latency_ms, 100)
        return {
            "previous_memory_usage_mb": previous_memory_usage_mb,
            "new_memory_usage_mb": service.memory_usage_mb,
            "status": service.status,
            "p95_latency_ms": service.p95_latency_ms,
        }, None

    return {}, f"Unsupported action_type '{action_type}'."


async def execute_remediation(
    service_name: str,
    action_type: str,
    parameters: dict[str, Any],
    idempotency_key: str,
    reason: str,
    thread_id: str = "mcp-direct",
    approved_by: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Execute an approved, audited remediation with idempotent replay protection.

    A repeated idempotency_key returns the recorded execution result without
    reapplying the mutation. `thread_id` and `approved_by` are internal audit
    context supplied by the LangGraph remediation node, not LLM-facing arguments.
    """
    try:
        validated = ExecuteRemediationInput(
            service_name=service_name,
            action_type=action_type,  # type: ignore[arg-type]
            parameters=parameters,
            idempotency_key=idempotency_key,
            reason=reason,
        )
    except ValidationError as err:
        return ToolErrorResponse(
            error_code="VALIDATION_ERROR",
            message=f"Invalid parameters for execute_remediation: {err.errors()[0]['msg']}",
            valid_services=list(KNOWN_SERVICES),
        ).model_dump()

    async with _get_session(session) as s:
        existing = await _fetch_execution(s, validated.idempotency_key)
        if existing is not None:
            return _cached_or_conflict(existing, validated)

        service = await s.get(InfraService, validated.service_name)
        if service is None:
            return ToolErrorResponse(
                error_code="SERVICE_NOT_FOUND",
                message=(
                    f"Service '{validated.service_name}' not found in infrastructure registry."
                ),
                valid_services=list(KNOWN_SERVICES),
            ).model_dump()

        details, mutation_error = _apply_remediation_mutation(
            service, validated.action_type, validated.parameters
        )
        if mutation_error is not None:
            return ToolErrorResponse(
                error_code="INVALID_PARAMETERS",
                message=mutation_error,
                valid_services=list(KNOWN_SERVICES),
            ).model_dump()

        executed_at = datetime.now(UTC)
        output = ExecuteRemediationOutput(
            status="success",
            action_type=validated.action_type,
            service_name=validated.service_name,
            idempotency_key=validated.idempotency_key,
            idempotent_replay=False,
            message=(
                f"Remediation '{validated.action_type}' executed on '{validated.service_name}'."
            ),
            details=details,
            executed_at=executed_at,
        )
        s.add(
            RemediationExecution(
                idempotency_key=validated.idempotency_key,
                thread_id=thread_id,
                service_name=validated.service_name,
                action_type=validated.action_type,
                parameters=validated.parameters,
                reason=validated.reason,
                approval_status="APPROVED",
                approved_by=approved_by,
                execution_result=output.model_dump(mode="json"),
                executed_at=executed_at,
            )
        )

        try:
            await s.flush()
            await s.commit()
        except IntegrityError:
            await s.rollback()
            existing = await _fetch_execution(s, validated.idempotency_key)
            if existing is not None:
                return _cached_or_conflict(existing, validated)
            raise

        return output.model_dump()
