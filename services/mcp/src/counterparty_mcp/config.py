"""Server-side MCP configuration; no model-controlled credentials or URLs."""

import os
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    """Limits and credentials of one internal report service process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    database_url: SecretStr | None = None
    auth_token_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    max_concurrent_reads: int = Field(default=5, ge=1, le=32)
    read_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_response_bytes: int = Field(default=65536, ge=4096, le=262144)

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Self:
        """Read configuration once at startup, failing closed without a token hash."""
        env = os.environ if environ is None else environ
        return cls.model_validate(
            {
                "database_url": env.get("MCP_DATABASE_URL") or None,
                "auth_token_sha256": env.get("MCP_AUTH_TOKEN_SHA256") or None,
                "max_concurrent_reads": env.get("MCP_MAX_CONCURRENT_READS", "5"),
                "read_timeout_seconds": env.get("MCP_READ_TIMEOUT_SECONDS", "10"),
                "max_response_bytes": env.get("MCP_MAX_RESPONSE_BYTES", "65536"),
            }
        )
