"""Unit tests for core settings, exceptions, and logger."""

import json
import logging
from pathlib import Path

import pytest

from src.common.config import Settings, get_settings, load_yaml_config
from src.common.exceptions import (
    CircuitBreakerOpenError,
    ConfigurationError,
    IdempotencyConflictError,
    OmniOpsBaseException,
    ServiceNotFoundError,
    StepLimitExceededError,
)
from src.common.logger import JSONFormatter, sanitize_log_record_data, setup_logger


def test_default_settings() -> None:
    """Test default values of application settings."""
    settings = Settings()
    assert settings.APP_NAME == "omniops-sre-agent"
    assert settings.ENV == "development"
    assert settings.LLM_MODEL_NAME == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert settings.LLM_BASE_URL == "http://localhost:8000/v1"
    assert settings.MAX_AGENT_STEPS == 6
    assert settings.MAX_AGENT_TOKENS == 4096
    assert settings.MAX_TOKENS == 4096
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert settings.OMNIDOC_RAG_URL == "http://localhost:8080/api/v1/query"


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test overriding settings via environment variables."""
    monkeypatch.setenv("APP_NAME", "omniops-test")
    monkeypatch.setenv("MAX_AGENT_STEPS", "10")
    monkeypatch.setenv("MAX_AGENT_TOKENS", "8192")
    override_settings = Settings()
    assert override_settings.APP_NAME == "omniops-test"
    assert override_settings.MAX_AGENT_STEPS == 10
    assert override_settings.MAX_AGENT_TOKENS == 8192
    assert override_settings.MAX_TOKENS == 8192


def test_settings_singleton() -> None:
    """Test cached get_settings returns identical object."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_load_yaml_config() -> None:
    """Test reading values from configs/config.yaml."""
    cfg = load_yaml_config("configs/config.yaml")
    assert isinstance(cfg, dict)
    assert cfg["app"]["name"] == "omniops-sre-agent"
    assert cfg["agent"]["max_steps"] == 6
    assert cfg["circuit_breaker"]["request_timeout_seconds"] == 2.5


def test_load_yaml_config_missing_file(tmp_path: Path) -> None:
    """Test ConfigurationError raised when config file does not exist."""
    missing_file = tmp_path / "non_existent.yaml"
    with pytest.raises(ConfigurationError) as exc_info:
        load_yaml_config(missing_file)
    assert exc_info.value.error_code == "CONFIGURATION_ERROR"


def test_load_yaml_config_malformed(tmp_path: Path) -> None:
    """Test ConfigurationError raised when YAML has invalid syntax."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("app: [unclosed bracket", encoding="utf-8")
    with pytest.raises(ConfigurationError) as exc_info:
        load_yaml_config(bad_yaml)
    assert exc_info.value.error_code == "CONFIGURATION_ERROR"
    assert "error" in exc_info.value.details


def test_exception_hierarchy() -> None:
    """Test domain exceptions and structured serialization."""
    base_err = OmniOpsBaseException("Something broke", error_code="ERR_CUSTOM", details={"k": "v"})
    err_dict = base_err.to_dict()
    assert err_dict["status"] == "error"
    assert err_dict["error_code"] == "ERR_CUSTOM"
    assert err_dict["message"] == "Something broke"
    assert err_dict["details"] == {"k": "v"}

    svc_err = ServiceNotFoundError("unknown-svc", valid_services=["auth", "payment"])
    assert svc_err.error_code == "SERVICE_NOT_FOUND"
    assert svc_err.details["service_name"] == "unknown-svc"
    assert svc_err.details["valid_services"] == ["auth", "payment"]

    idem_err = IdempotencyConflictError("idem_123")
    assert idem_err.error_code == "ERR_IDEMPOTENCY_CONFLICT"
    assert idem_err.details["idempotency_key"] == "idem_123"

    cb_err = CircuitBreakerOpenError("omnidoc_rag")
    assert cb_err.error_code == "ERR_CIRCUIT_BREAKER_OPEN"

    step_err = StepLimitExceededError(step_count=7, max_steps=6)
    assert step_err.error_code == "ERR_STEP_LIMIT_EXCEEDED"
    assert step_err.details["step_count"] == 7


def test_sanitize_log_record_data() -> None:
    """Test sensitive field masking."""
    data = {
        "api_key": "super-secret-key",
        "authorization": "Bearer token123",
        "nested": {
            "password": "mypassword",
            "safe_field": "visible_data",
        },
        "items": [{"secret_token": "hidden"}, {"name": "svc"}],
    }
    sanitized = sanitize_log_record_data(data)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["safe_field"] == "visible_data"
    assert sanitized["items"][0]["secret_token"] == "[REDACTED]"
    assert sanitized["items"][1]["name"] == "svc"


def test_logger_setup_and_json_formatter() -> None:
    """Test setting up logger and JSON formatting output."""
    logger = setup_logger("test_omniops_logger", level="DEBUG", json_format=True)
    assert logger.name == "test_omniops_logger"
    assert logger.level == logging.DEBUG

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Test message with param: %s and Bearer eyJhbGciOiJIUzI1NiJ9",
        args=("foo",),
        exc_info=None,
    )
    record.__dict__["correlation_id"] = "corr-12345"
    record.__dict__["service_name"] = "payment-api"
    record.__dict__["extra_data"] = {"api_key": "secret_abc", "status": "ok"}

    formatted_json = formatter.format(record)
    parsed = json.loads(formatted_json)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Test message with param: foo and Bearer [REDACTED]"
    assert parsed["correlation_id"] == "corr-12345"
    assert parsed["service_name"] == "payment-api"
    assert parsed["extra_data"]["api_key"] == "[REDACTED]"
    assert parsed["extra_data"]["status"] == "ok"
