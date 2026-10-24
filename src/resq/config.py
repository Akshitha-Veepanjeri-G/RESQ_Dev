from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Authoritative system configuration for RESQ Dev."""

    # Docker Execution Sandbox
    docker_image_name: str = Field(
        default="resq-sandbox:latest",
        validation_alias=AliasChoices("resq_docker_image_name", "docker_image_name"),
        description="Docker image tag used for isolated code execution.",
    )
    max_execution_timeout_seconds: int = Field(
        default=10,
        validation_alias=AliasChoices("resq_max_execution_timeout_seconds", "max_execution_timeout_seconds"),
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
    agent_max_cycles: int = Field(
        default=8,
        ge=1,
        le=20,
        validation_alias=AliasChoices("resq_agent_max_cycles", "agent_max_cycles"),
        description="Maximum decision cycles for the autonomous verification agent.",
    )
    agent_max_tool_calls: int = Field(
        default=12,
        ge=1,
        le=30,
        validation_alias=AliasChoices("resq_agent_max_tool_calls", "agent_max_tool_calls"),
        description="Maximum tool invocations permitted per verification job.",
    )

    # Replaceable LLM Gateway Configuration
    llm_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices("resq_llm_provider", "llm_provider"),
        description="Active LLM provider adapter: 'mock', 'gemini', 'openai', or 'anthropic'.",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("resq_gemini_api_key", "gemini_api_key", "google_api_key"),
        description="API key for Google Gemini provider (optional).",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("resq_gemini_model", "gemini_model"),
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
        env_file=(str(DOTENV_PATH), ".env"),
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
