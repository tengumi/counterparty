"""Environment-backed configuration for the agent service."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DETERMINISTIC_PROVIDER = "deterministic"
"""Provider name of the built-in adapter that needs no model API."""


class AgentSettings(BaseSettings):
    """Configuration loaded at the application composition boundary."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    service_name: str = "counterparty-agent"
    postgres_dsn: SecretStr | None = None

    model_provider: str = DETERMINISTIC_PROVIDER
    """LangChain provider id, or ``deterministic`` for the built-in adapter.

    The default keeps the service buildable and testable without a model API
    key; a real demo names its provider and model id through configuration.
    """

    model_id: str = "counterparty-deterministic-v1"
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_max_tokens: int | None = Field(default=None, ge=1)

    mcp_url: str | None = None
    """Streamable HTTP endpoint of the internal reports MCP service."""

    mcp_auth_token: SecretStr | None = None
    mcp_timeout_seconds: float = Field(default=20.0, gt=0)

    ui_api_url: str | None = None
    """Base URL of the UI backend, for the internal add-company endpoint."""

    ui_api_internal_token: SecretStr | None = None
    """Shared secret for the UI backend's internal, session-less endpoints."""

    client_profile_json: str | None = None
    """JSON override for the signed-in client's base profile; the demo client
    (``harness.client_profile.DEMO_CLIENT``) is used when unset or malformed."""

    max_tool_calls: int = Field(default=12, ge=1)
    """Engineering default from Specs 04 §3; not a measured product norm."""

    run_timeout_seconds: float = Field(default=120.0, gt=0)
