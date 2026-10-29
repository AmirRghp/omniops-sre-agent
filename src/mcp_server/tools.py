"""Model Context Protocol (MCP) tool implementations for OmniOps SRE Agent.

Defines the core diagnostic and research tools:
- get_service_health: Read-only inspection of microservice metrics and state.
- query_incident_logs: Read-only query of operational error logs with prompt injection defense.
- search_runbooks: Read-only runbook search with circuit breaker fallback.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logger import setup_logger
from src.db.models import IncidentLog, InfraService
from src.db.session import session_scope
from src.mcp_server.runbook_client import RunbookClient
from src.mcp_server.schemas import (
    KNOWN_SERVICES,
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
        return clean_msg
    return f"<untrusted_log_data>{clean_msg}</untrusted_log_data>"


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
