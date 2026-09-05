"""Demo sign-in and the session endpoints of the UI backend.

The sign-in itself is demonstrative: a login from a server-side list is accepted
without a credential, and the response says so in ``demo``. Nothing else about
it is pretend. The session it issues is a real server-side session, its tenant
and user are the real inputs to every ownership check, and the token lives only
in an ``HttpOnly`` cookie the page's JavaScript cannot read.

The token is never returned in a body, so it cannot be copied into local storage
or a log by a well-meaning client.
"""

from typing import Annotated

from counterparty_contracts import ErrorCode, TenantId, UserId
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..dependencies import CurrentSession, get_session_store, get_settings
from ..errors import ApiError
from ..sessions import Session, SessionStore, utc_now

__all__ = ["DemoSignInRequest", "SessionResponse", "router"]

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class DemoSignInRequest(BaseModel):
    """Choose one of the demo identities provisioned on the server."""

    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=64)


class SessionResponse(BaseModel):
    """Who the caller is, as the server sees them.

    The session token is not part of this body: it stays in the ``HttpOnly``
    cookie.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: TenantId
    user_id: UserId
    login: str
    display_name: str
    expires_at: str
    demo: bool = True
    """``True`` while the sign-in is the demo one; it never means "verified"."""


def _read_token(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> str | None:
    """Return the raw session token of the request, if it carries one."""
    return request.cookies.get(settings.session_cookie_name)


def _as_response(session: Session) -> SessionResponse:
    """Render a session without exposing anything that opens it."""
    return SessionResponse(
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        login=session.login,
        display_name=session.display_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def sign_in(
    payload: DemoSignInRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> SessionResponse:
    """Open a session for one of the configured demo identities.

    Raises:
        ApiError: If demo sign-in is switched off, or the login is not one of
            the provisioned demo identities.
    """
    if not settings.demo_auth_enabled:
        raise ApiError(ErrorCode.FORBIDDEN, "demo sign-in is disabled")
    identity = settings.demo_tenant_of(payload.login)
    if identity is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "unknown demo login")

    issued = await sessions.create(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        login=payload.login,
        display_name=identity.display_name,
        ttl_seconds=settings.session_ttl_seconds,
        now=utc_now(),
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=issued.token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return _as_response(issued.session)


@router.get("/session", response_model=SessionResponse)
async def current_session(session: CurrentSession) -> SessionResponse:
    """Report the caller of the current session."""
    return _as_response(session)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    session_token: Annotated[str | None, Depends(_read_token)],
) -> None:
    """Drop the session server-side and clear the cookie.

    Signing out without a session is not an error: the result is the same.
    """
    if session_token is not None:
        await sessions.revoke(session_token)
    response.delete_cookie(key=settings.session_cookie_name, path="/")
