"""Configuration management for RESQ Dev using Pydantic Settings."""

from functools import lru_cache
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Authoritative system configuration for RESQ Dev."""

    # Docker Execution Sandbox
    docker_image_name: str = Field(
        default="resq-sandbox:latest",
        description="Docker image tag used for isolated code execution.",
    )
    max_execution_timeout_seconds: int = Field(
        default=10,
        description="Hard execution timeout in seconds enforced by host runner.",
    )
    docker_memory_limit: str = Field(
        default="512m",
        description="Hard memory ceiling for the sandbox container.",
    )
    docker_cpu_limit: float = Field(
        default=1.0,
        description="CPU core quota allocated to the sandbox container.",
    )
    docker_pids_limit: int = Field(
        default=64,
        description="Maximum process count inside the sandbox container.",
    )
    docker_max_output_bytes: int = Field(
        default=65_536,
        ge=1024,
        le=10_485_760,
        description="Maximum bytes of stdout or stderr captured from sandbox container before truncation.",
    )

    # Verification Pipeline Constraints
    max_repair_cycles: int = Field(
        default=1,
        description="Maximum repair/retry attempts before halting. Hard maximum of 2.",
    )

    # Replaceable LLM Gateway Configuration
    llm_provider: str = Field(
        default="mock",
        description="Active LLM provider adapter: 'mock', 'gemini', 'openai', or 'anthropic'.",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        description="API key for Google Gemini provider (optional).",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model tag for code repair synthesis.",
    )
    llm_request_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="Hard timeout in seconds for LLM API requests.",
    )
    llm_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Sampling temperature for code repair synthesis.",
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="API key for OpenAI provider (optional).",
    )
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="API key for Anthropic provider (optional).",
    )

    # Persistence Configuration (Milestone 3)
    database_url: str = Field(
        default="sqlite:///./resq.db",
        description="SQLite database connection URL.",
    )
    api_host: str = Field(
        default="127.0.0.1",
        description="FastAPI host binding (loopback default).",
    )
    api_port: int = Field(
        default=8000,
        description="FastAPI port binding.",
    )
    max_request_body_bytes: int = Field(
        default=524_288,
        description="Maximum allowed HTTP request body in bytes (512 KiB).",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("max_execution_timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_execution_timeout_seconds must be positive")
        if v > 60:
            raise ValueError("max_execution_timeout_seconds cannot exceed 60 seconds")
        return v

    @field_validator("max_repair_cycles")
    @classmethod
    def validate_repair_cycles(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_repair_cycles must be at least 1")
        if v > 2:
            raise ValueError("max_repair_cycles cannot exceed 2 (bounded human-supervised repair)")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns cached singleton Settings instance."""
    return Settings()
