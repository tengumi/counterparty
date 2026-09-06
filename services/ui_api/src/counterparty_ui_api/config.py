"""Process configuration of the UI backend.

Everything security-relevant is decided here, on the server: who may sign in for
the demo, how long a session lives and how its cookie is transported. Nothing in
this module is sent to the browser, and no value here is ever accepted from a
request body.
"""

import json
import os
from typing import Self

from counterparty_contracts import TenantId, UserId
from pydantic import BaseModel, ConfigDict, Field, SecretStr

__all__ = ["DATABASE_URL_ENV", "DEMO_USERS_ENV", "DemoUser", "Settings"]

DEMO_USERS_ENV = "UI_API_DEMO_USERS"
"""JSON mapping of login to ``{tenant_id, user_id, display_name}``."""

DATABASE_URL_ENV = "UI_API_DATABASE_URL"
"""Async PostgreSQL URL the service connects with.

The connection is made as the ``counterparty_ui_api`` role: it reads both
schemas and writes only ``workspace``. The service does not re-implement that
restriction, and it must not be handed a wider role to work around it.
"""

_SESSION_TTL_ENV = "UI_API_SESSION_TTL_SECONDS"
_POOL_SIZE_ENV = "UI_API_DATABASE_POOL_SIZE"
_COOKIE_NAME_ENV = "UI_API_SESSION_COOKIE"
_COOKIE_SECURE_ENV = "UI_API_SESSION_COOKIE_SECURE"
_DEMO_AUTH_ENV = "UI_API_DEMO_AUTH"
_INTERNAL_TOKEN_ENV = "UI_API_INTERNAL_TOKEN"
_AGENT_URL_ENV = "UI_API_AGENT_URL"

_DEFAULT_DEMO_USERS: dict[str, dict[str, str]] = {
    "demo-analyst": {
        "tenant_id": "00000000-0000-4000-8000-0000000000e1",
        "user_id": "00000000-0000-4000-8000-0000000000a1",
        "display_name": "Демо-аналитик",
    },
    "demo-partner": {
        "tenant_id": "00000000-0000-4000-8000-0000000000e2",
        "user_id": "00000000-0000-4000-8000-0000000000a2",
        "display_name": "Демо-партнёр",
    },
}
"""Two logins in two different tenants, so isolation is demonstrable."""


class DemoUser(BaseModel):
    """One pre-provisioned demo identity.

    A demo identity proves nothing about a real person. It exists so the rest
    of the API can be exercised with a genuine tenant and user scope; the
    ownership checks it feeds are real.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    user_id: UserId
    display_name: str = Field(min_length=1)


class Settings(BaseModel):
    """Server-side settings of one UI backend process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    demo_auth_enabled: bool = True
    """Whether the demo sign-in endpoint is mounted at all."""

    demo_users: dict[str, DemoUser] = Field(default_factory=dict)
    session_ttl_seconds: int = Field(default=8 * 60 * 60, ge=60)
    session_cookie_name: str = Field(default="cp_session", min_length=1)
    session_cookie_secure: bool = True
    """``False`` only for local HTTP development; the cookie is always
    ``HttpOnly`` and ``SameSite=Lax`` regardless."""

    database_url: str | None = None
    """``None`` in a process that serves only health and session endpoints; a
    project request then refuses with ``dependency_unavailable`` instead of
    pretending that the workspace is empty."""

    database_pool_size: int = Field(default=5, ge=1)

    internal_token: SecretStr | None = None
    """Shared secret for session-less internal endpoints (the agent add-company
    call). ``None`` leaves those endpoints refusing every request."""

    agent_url: str | None = None
    """Base URL of the agent service, for the report-screen summary call.
    ``None`` makes the summary endpoint report the feature as unavailable."""

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Self:
        """Build settings from the process environment.

        Args:
            environ: Environment to read; defaults to ``os.environ``.

        Returns:
            The parsed settings.

        Raises:
            ValueError: If the demo user mapping is not valid JSON.
        """
        env = dict(os.environ) if environ is None else environ
        raw_users = env.get(DEMO_USERS_ENV)
        if raw_users is None:
            users_payload: object = _DEFAULT_DEMO_USERS
        else:
            try:
                users_payload = json.loads(raw_users)
            except json.JSONDecodeError as error:
                raise ValueError(f"{DEMO_USERS_ENV} must be a JSON object") from error
        return cls.model_validate(
            {
                "demo_auth_enabled": _flag(env, _DEMO_AUTH_ENV, default=True),
                "demo_users": users_payload,
                "session_ttl_seconds": int(env.get(_SESSION_TTL_ENV, 8 * 60 * 60)),
                "session_cookie_name": env.get(_COOKIE_NAME_ENV, "cp_session"),
                "session_cookie_secure": _flag(env, _COOKIE_SECURE_ENV, default=True),
                "database_url": env.get(DATABASE_URL_ENV) or None,
                "database_pool_size": int(env.get(_POOL_SIZE_ENV, 5)),
                "internal_token": env.get(_INTERNAL_TOKEN_ENV) or None,
                "agent_url": env.get(_AGENT_URL_ENV) or None,
            }
        )

    def demo_tenant_of(self, login: str) -> DemoUser | None:
        """Return the demo identity of a login, if it is provisioned."""
        return self.demo_users.get(login)


def _flag(env: dict[str, str], name: str, *, default: bool) -> bool:
    """Read a boolean flag, treating an unset variable as its default."""
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
