"""Fault injection suite for evaluating autonomous agent self-healing and error recovery."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from src.mcp_server.schemas import KNOWN_SERVICES

VALID_SERVICES: list[str] = list(KNOWN_SERVICES)


class FaultType(StrEnum):
    """Supported fault injection modes for diagnostic tools."""

    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    CORRUPTED_PAYLOAD = "CORRUPTED_PAYLOAD"


class InjectedFaultRecord(BaseModel):
    """Audit record of an injected fault."""

    tool_name: str
    fault_type: FaultType
    injected_payload: dict[str, Any]
    recovered: bool = False


class FaultInjector:
    """Simulates realistic tool failures to measure agent recovery determinism."""

    def __init__(self) -> None:
        self.records: list[InjectedFaultRecord] = []

    def create_fault_response(
        self,
        tool_name: str,
        fault_type: FaultType,
        attempted_service: str = "unknown-service",
    ) -> dict[str, Any]:
        """Generate structured error dictionary matching FastMCP error contract."""
        payload: dict[str, Any]
        if fault_type == FaultType.SERVICE_NOT_FOUND:
            payload = {
                "status": "error",
                "error_code": "SERVICE_NOT_FOUND",
                "message": f"Service '{attempted_service}' does not exist.",
                "valid_services": VALID_SERVICES,
            }
        elif fault_type == FaultType.TOOL_TIMEOUT:
            payload = {
                "status": "error",
                "error_code": "TOOL_TIMEOUT",
                "message": f"Tool '{tool_name}' timed out after 5.0 seconds.",
            }
        elif fault_type == FaultType.TRANSIENT_ERROR:
            payload = {
                "status": "error",
                "error_code": "TOOL_EXECUTION_ERROR",
                "message": f"Transient database connection failure in '{tool_name}'.",
            }
        else:
            payload = {
                "status": "error",
                "error_code": "CORRUPTED_PAYLOAD",
                "message": "Malformed response payload from upstream service.",
            }

        self.records.append(
            InjectedFaultRecord(
                tool_name=tool_name,
                fault_type=fault_type,
                injected_payload=payload,
            )
        )
        return payload

    def mark_recovery(self, index: int = -1, recovered: bool = True) -> None:
        """Mark whether the agent successfully self-corrected on subsequent turns."""
        if self.records:
            self.records[index].recovered = recovered

    @property
    def total_injected(self) -> int:
        """Total number of faults injected."""
        return len(self.records)

    @property
    def total_recovered(self) -> int:
        """Total number of successful self-corrections."""
        return sum(1 for r in self.records if r.recovered)

    @property
    def recovery_rate(self) -> float:
        """Percentage of injected faults that were successfully recovered."""
        if not self.records:
            return 100.0
        return (self.total_recovered / self.total_injected) * 100.0
