"""Structured logging configuration for OmniOps SRE Agent."""

import json
import logging
import re
import sys
from typing import Any

# Sensitive field keys to redact from logs
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"api[-_]?key", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
]

# Patterns for inline textual secrets (e.g. Bearer eyJ..., token=...)
INLINE_SECRET_PATTERNS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"\1[REDACTED]"),
    (
        re.compile(r"(api[_-]?key\s*[=:]\s*['\"]?)[A-Za-z0-9\-_]+(['\"]?)", re.IGNORECASE),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(r"(password\s*[=:]\s*['\"]?)[^\s'\"]+(['\"]?)", re.IGNORECASE),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(r"(token\s*[=:]\s*['\"]?)[A-Za-z0-9\-._~+/]+=*(['\"]?)", re.IGNORECASE),
        r"\1[REDACTED]\2",
    ),
]


def sanitize_message_text(message: str) -> str:
    """Mask inline secrets in raw text messages."""
    sanitized = message
    for pattern, replacement in INLINE_SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_log_record_data(data: Any) -> Any:
    """Recursively mask sensitive values in dictionaries and lists."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            if any(pattern.search(key) for pattern in SENSITIVE_KEY_PATTERNS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_log_record_data(value)
        return sanitized
    if isinstance(data, list):
        return [sanitize_log_record_data(item) for item in data]
    return data


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        raw_message = record.getMessage()
        log_payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_message_text(raw_message),
        }

        # Include standard extra fields if present
        if hasattr(record, "correlation_id"):
            log_payload["correlation_id"] = record.correlation_id

        if hasattr(record, "service_name"):
            log_payload["service_name"] = record.service_name

        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_payload["extra_data"] = sanitize_log_record_data(record.extra_data)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Format log records as human-readable text while masking inline secrets."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return sanitize_message_text(formatted)


def setup_logger(
    name: str = "omniops",
    level: str = "INFO",
    json_format: bool = False,
) -> logging.Logger:
    """Configure and return a structured logger.

    Args:
        name: Logger identifier.
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_format: If True, log in structured JSON format; otherwise standard text.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level.upper())

    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level.upper())

        if json_format:
            formatter: logging.Formatter = JSONFormatter()
        else:
            formatter = TextFormatter(
                fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
