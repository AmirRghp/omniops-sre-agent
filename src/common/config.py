"""Core application settings and YAML configuration loader."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.common.exceptions import ConfigurationError


class Settings(BaseSettings):
    """Application runtime settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "omniops-sre-agent"
    ENV: str = "development"

    # LLM / vLLM Configuration
    LLM_BASE_URL: str = "http://localhost:8000/v1"
    LLM_MODEL_NAME: str = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    LLM_API_KEY: str = "EMPTY"

    # PostgreSQL 16
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/omniops"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/omniops"

    # Project 1 Circuit Breaker & Fallback
    OMNIDOC_RAG_URL: str = "http://localhost:8080/api/v1/query"
    FALLBACK_RUNBOOKS_PATH: str = "data/fallback_runbooks.json"

    # Agent Constraints & Limits
    MAX_AGENT_STEPS: int = Field(default=6, ge=1, le=20)
    MAX_AGENT_TOKENS: int = Field(default=4096, ge=512, le=32768)
    API_KEY: str = "dev-secret-key-12345"

    # Observability (Langfuse)
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "http://localhost:3000"

    # Config YAML Path
    CONFIG_PATH: str = "configs/config.yaml"


def load_yaml_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration dictionary from YAML file safely.

    Args:
        path: Optional path to YAML configuration. Defaults to configs/config.yaml.

    Returns:
        dict[str, Any]: Parsed configuration tree.

    Raises:
        ConfigurationError: If the YAML file does not exist or has invalid syntax.
    """
    config_file = Path(path) if path else Path("configs/config.yaml")

    if not config_file.exists():
        raise ConfigurationError(
            f"Configuration file not found: {config_file}",
            details={"path": str(config_file)},
        )

    try:
        with open(config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"Failed to parse YAML configuration: {exc}",
            details={"path": str(config_file), "error": str(exc)},
        ) from exc


@lru_cache
def get_settings() -> Settings:
    """Provide cached singleton instance of application settings."""
    return Settings()
