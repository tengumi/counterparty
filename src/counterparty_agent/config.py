"""Типизированная конфигурация из переменных окружения и локального файла .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения; секреты маскируются в представлениях и журналах."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="COUNTERPARTY_",
        case_sensitive=False,
        extra="ignore",
    )

    llm_model: str = "qwen3.7-plus"
    llm_base_url: AnyHttpUrl = AnyHttpUrl("https://api.dslab.tech/v1")
    llm_api_key: SecretStr | None = None
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_max_tokens: int = Field(default=1200, ge=1, le=64_000)
    llm_timeout_seconds: float = Field(default=90, ge=1, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_reasoning_enabled: bool = False

    snapshot_json_path: Path = Path("data/snapshot.json")
    snapshot_csv_path: Path | None = None
    session_db_path: Path = Path("data/sessions.sqlite3")
    session_ttl_seconds: int = Field(default=86_400, ge=60)
    agent_path: str = "/agent"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    log_level: str = "INFO"

    @property
    def llm_configured(self) -> bool:
        """Проверить наличие ключа, не раскрывая его значение."""

        return bool(self.llm_api_key and self.llm_api_key.get_secret_value().strip())

    def require_llm_api_key(self) -> str:
        """Вернуть API-ключ или безопасную ошибку с инструкцией по исправлению."""

        if not self.llm_configured or self.llm_api_key is None:
            raise ValueError(
                "COUNTERPARTY_LLM_API_KEY is missing. Copy .env.example to .env and add the key."
            )
        return self.llm_api_key.get_secret_value()

    @property
    def normalized_llm_base_url(self) -> str:
        """Вернуть базовый URL для OpenAI-совместимого клиента."""

        return str(self.llm_base_url).rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Создать настройки один раз на процесс."""

    return Settings()
