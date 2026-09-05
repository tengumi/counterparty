"""Server-side sessions of the UI backend.

The browser holds one opaque token in an ``HttpOnly`` cookie and nothing else:
no tenant, no user id, no signed claim it could edit. Everything the API trusts
lives here, on the server, and is looked up by the token.

The token itself is never stored. Only its SHA-256 digest is kept, so a dump of
the session store cannot be replayed as a set of live cookies. A session is
issued for a demo identity, but the tenant and user it carries are real inputs
to the ownership checks that follow.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from counterparty_contracts import TenantId, UserId

__all__ = ["InMemorySessionStore", "IssuedSession", "Session", "SessionStore"]

_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class Session:
    """One authenticated caller, as the server knows them."""

    tenant_id: TenantId
    user_id: UserId
    login: str
    display_name: str
    issued_at: datetime
    expires_at: datetime

    def is_expired(self, *, now: datetime) -> bool:
        """Whether the session may no longer authorize anything."""
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly created session together with the token that opens it.

    The token exists only on the way to the ``Set-Cookie`` header: it is not
    stored, not logged and not echoed in a response body.
    """

    token: str
    session: Session


class SessionStore(Protocol):
    """Where sessions live between requests."""

    async def create(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
        login: str,
        display_name: str,
        ttl_seconds: int,
        now: datetime,
    ) -> IssuedSession:
        """Issue a new session and return it with its one-time token."""
        ...

    async def resolve(self, token: str, *, now: datetime) -> Session | None:
        """Return the live session a token opens, or ``None``."""
        ...

    async def revoke(self, token: str) -> None:
        """Drop a session; revoking an unknown token is not an error."""
        ...


def _digest(token: str) -> str:
    """Return the stored form of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InMemorySessionStore:
    """Process-local session store.

    It is enough for one MVP process and loses every session on restart, which
    is an honest limitation rather than a hidden one: the user signs in again.
    """

    def __init__(self) -> None:
        """Start with no sessions."""
        self._sessions: dict[str, Session] = {}

    async def create(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
        login: str,
        display_name: str,
        ttl_seconds: int,
        now: datetime,
    ) -> IssuedSession:
        """Issue a session for an already authenticated identity."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        session = Session(
            tenant_id=tenant_id,
            user_id=user_id,
            login=login,
            display_name=display_name,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._sessions[_digest(token)] = session
        return IssuedSession(token=token, session=session)

    async def resolve(self, token: str, *, now: datetime) -> Session | None:
        """Return the live session behind a token, dropping an expired one."""
        key = _digest(token)
        session = self._sessions.get(key)
        if session is None:
            return None
        if session.is_expired(now=now):
            del self._sessions[key]
            return None
        return session

    async def revoke(self, token: str) -> None:
        """Forget a session, if the token opens one."""
        self._sessions.pop(_digest(token), None)


def utc_now() -> datetime:
    """Return the current instant in UTC."""
    return datetime.now(UTC)
