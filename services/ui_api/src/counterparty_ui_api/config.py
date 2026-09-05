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
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["DEMO_USERS_ENV", "DemoUser", "Settings"]

DEMO_USERS_ENV = "UI_API_DEMO_USERS"
"""JSON mapping of login to ``{tenant_id, user_id, display_name}``."""

_SESSION_TTL_ENV = "UI_API_SESSION_TTL_SECONDS"
_COOKIE_NAME_ENV = "UI_API_SESSION_COOKIE"
_COOKIE_SECURE_ENV = "UI_API_SESSION_COOKIE_SECURE"
_DEMO_AUTH_ENV = "UI_API_DEMO_AUTH"

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
