"""Environment-backed configuration for the agent service."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Configuration loaded at the application composition boundary."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    service_name: str = "counterparty-agent"
    postgres_dsn: SecretStr | None = None
