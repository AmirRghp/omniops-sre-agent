"""Custom exceptions for OmniOps SRE Agent."""

from typing import Any


class OmniOpsBaseException(Exception):
    """Base exception for all domain-specific errors in OmniOps SRE Agent."""

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to structured dictionary format."""
        return {
            "status": "error",
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(OmniOpsBaseException):
    """Raised when configuration is missing, malformed, or invalid."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)


class DatabaseError(OmniOpsBaseException):
    """Raised when a database query or connection failure occurs."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="DATABASE_ERROR", details=details)


class ServiceNotFoundError(OmniOpsBaseException):
    """Raised when an unknown infrastructure service is requested."""

    def __init__(
        self,
        service_name: str,
        valid_services: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["service_name"] = service_name
        if valid_services is not None:
            merged_details["valid_services"] = valid_services
        super().__init__(
            f"Service '{service_name}' not found in registered infrastructure services.",
            error_code="ERR_UNKNOWN_SERVICE",
            details=merged_details,
        )


class IdempotencyConflictError(OmniOpsBaseException):
    """Raised when an idempotency key conflict occurs during remediation."""

    def __init__(
        self,
        idempotency_key: str,
        message: str = "Idempotency key conflict.",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["idempotency_key"] = idempotency_key
        super().__init__(
            message,
            error_code="ERR_IDEMPOTENCY_CONFLICT",
            details=merged_details,
        )


class CircuitBreakerOpenError(OmniOpsBaseException):
    """Raised when the circuit breaker for external service is open."""

    def __init__(
        self,
        service_target: str,
        message: str = "Circuit breaker is open for external service.",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = details or {}
        merged_details["service_target"] = service_target
        super().__init__(
            message,
            error_code="ERR_CIRCUIT_BREAKER_OPEN",
            details=merged_details,
        )


class RemediationExecutionError(OmniOpsBaseException):
    """Raised when remediation mutation execution fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, error_code="ERR_REMEDIATION_FAILED", details=details)


class StepLimitExceededError(OmniOpsBaseException):
    """Raised when agent exceeds the configured maximum reasoning step ceiling."""

    def __init__(self, step_count: int, max_steps: int) -> None:
        super().__init__(
            f"Agent exceeded maximum reasoning steps ({step_count}/{max_steps}).",
            error_code="ERR_STEP_LIMIT_EXCEEDED",
            details={"step_count": step_count, "max_steps": max_steps},
        )
