"""FastMCP entrypoint for the OmniOps SRE tool server.

Run over stdio for IDE clients (Cursor, Claude Desktop):
    python -m src.mcp_server.server --transport stdio

Or over SSE for HTTP clients:
    python -m src.mcp_server.server --transport sse
"""

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.mcp_server import tools
from src.mcp_server.schemas import LogSeverity, RemediationActionType, RunbookCategory

mcp = FastMCP("omniops-sre-mcp")


@mcp.tool()
async def search_runbooks(
    query: str,
    category: RunbookCategory | None = None,
) -> dict[str, Any]:
    """Search troubleshooting runbooks via OmniDoc RAG or the local fallback."""
    return await tools.search_runbooks(query=query, category=category)


@mcp.tool()
async def query_incident_logs(
    service_name: str,
    severity: LogSeverity = "ERROR",
    limit: int = 5,
) -> dict[str, Any]:
    """Fetch recent structured logs for a specific microservice from PostgreSQL."""
    return await tools.query_incident_logs(
        service_name=service_name,
        severity=severity,
        limit=limit,
    )


@mcp.tool()
async def get_service_health(service_name: str) -> dict[str, Any]:
    """Retrieve real-time resource utilization, replica counts, connection pools, and status."""
    return await tools.get_service_health(service_name=service_name)


@mcp.tool()
async def execute_remediation(
    service_name: str,
    action_type: RemediationActionType,
    parameters: dict[str, Any],
    idempotency_key: str,
    reason: str,
) -> dict[str, Any]:
    """Execute an approved, idempotent remediation and record it in the audit ledger."""
    return await tools.execute_remediation(
        service_name=service_name,
        action_type=action_type,
        parameters=parameters,
        idempotency_key=idempotency_key,
        reason=reason,
    )


def main() -> None:
    """Parse CLI arguments and serve the four MCP tools over the selected transport."""
    parser = argparse.ArgumentParser(
        prog="omniops-sre-mcp",
        description="OmniOps SRE Agent MCP server exposing four narrow SRE tools.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default="stdio",
        help="MCP transport to serve (default: stdio).",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
