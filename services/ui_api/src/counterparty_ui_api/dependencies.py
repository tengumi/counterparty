"""The scope every project operation is executed in.

A request carries an opaque session cookie and a project id in its path. The
dependencies here turn that into a :class:`ProjectScope`: a tenant, a user and a
project the server has verified belong together. Nothing downstream has to
repeat the check, and no handler can accidentally skip it by trusting a body
field instead.

A project of another tenant is reported as ``not_found``: a wrong answer would
tell a prober that it exists.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID

from counterparty_contracts import ErrorCode, ProjectId, TenantId, ThreadId, UserId
from counterparty_storage import AsyncUnitOfWork, TenantScope, unit_of_work
from fastapi import Depends, Path, Request

from .config import Settings
from .database import SessionFactory
from .errors import ApiError
from .sessions import Session, SessionStore, utc_now
from .workspace import ProjectDirectory, StorageProjectDirectory

__all__ = [
    "CurrentSession",
    "ProjectScope",
    "ScopedProject",
    "ScopedThread",
    "TenantWork",
    "get_project_directory",
    "get_session_store",
    "get_settings",
    "get_unit_of_work",
    "require_project_scope",
    "require_session",
    "require_thread_scope",
    "require_unit_of_work",
]


def get_settings(request: Request) -> Settings:
    """Return the settings of this application."""
    return cast(Settings, request.app.state.settings)


def get_session_store(request: Request) -> SessionStore:
    """Return the session store of this application."""
    return cast(SessionStore, request.app.state.session_store)


def get_session_factory(request: Request) -> SessionFactory | None:
    """Return the database session factory, or ``None`` without a database."""
    return cast(SessionFactory | None, getattr(request.app.state, "session_factory", None))


async def require_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> Session:
    """Resolve the caller from their session cookie.

    Raises:
        ApiError: If no live session backs the request.
    """
    token = request.cookies.get(settings.session_cookie_name)
    session = None if token is None else await sessions.resolve(token, now=utc_now())
    if session is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "a valid session is required")
    return session


CurrentSession = Annotated[Session, Depends(require_session)]


async def get_unit_of_work(
    session: CurrentSession,
    factory: Annotated[SessionFactory | None, Depends(get_session_factory)],
) -> AsyncIterator[AsyncUnitOfWork | None]:
    """Open one transaction for the caller's tenant, for the whole request.

    FastAPI resolves this dependency once per request, so the ownership check
    and the work it guards read the same transaction rather than two.

    Nothing commits by itself: a handler that raises leaves the transaction
    rolled back and therefore leaves no half-written project behind.

    Yields:
        The unit of work, or ``None`` in a process configured without a
        database. The refusal for that case is raised by
        :func:`require_unit_of_work`, so a route that needs no storage still
        works.
    """
    if factory is None:
        yield None
        return
    scope = TenantScope(
        tenant_id=UUID(str(session.tenant_id)),
        actor_user_id=UUID(str(session.user_id)),
    )
    async with unit_of_work(factory, scope) as uow:
        yield uow


def require_unit_of_work(
    uow: Annotated[AsyncUnitOfWork | None, Depends(get_unit_of_work)],
) -> AsyncUnitOfWork:
    """Return the transaction of this request.

    Raises:
        ApiError: If the process runs without a database. An unavailable
            dependency is reported as such; it never becomes an empty result.
    """
    if uow is None:
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "the workspace storage is not available",
            retryable=True,
        )
    return uow


TenantWork = Annotated[AsyncUnitOfWork, Depends(require_unit_of_work)]


def get_project_directory(
    request: Request,
    uow: Annotated[AsyncUnitOfWork | None, Depends(get_unit_of_work)],
) -> ProjectDirectory:
    """Return the ownership directory this request is checked against.

    An application built with an explicit directory keeps it; otherwise the
    directory reads the tenant-scoped repositories of this request.

    Raises:
        ApiError: If neither a directory nor a database is configured.
    """
    override = getattr(request.app.state, "project_directory", None)
    if override is not None:
        return cast(ProjectDirectory, override)
    return StorageProjectDirectory(require_unit_of_work(uow))


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """A verified tenant, user and project, optionally one of its threads."""

    tenant_id: TenantId
    user_id: UserId
    project_id: ProjectId
    thread_id: ThreadId | None = None


async def require_project_scope(
    session: CurrentSession,
    projects: Annotated[ProjectDirectory, Depends(get_project_directory)],
    project_id: Annotated[ProjectId, Path()],
) -> ProjectScope:
    """Verify that the caller's session actually owns this project.

    Raises:
        ApiError: If the project does not exist, belongs to another tenant or
            to another user. All three are reported as ``not_found``.
    """
    record = await projects.find_project(project_id)
    if (
        record is None
        or record.tenant_id != session.tenant_id
        or record.owner_user_id != session.user_id
    ):
        raise ApiError(ErrorCode.NOT_FOUND, "project not found")
    return ProjectScope(tenant_id=session.tenant_id, user_id=session.user_id, project_id=project_id)


ScopedProject = Annotated[ProjectScope, Depends(require_project_scope)]


async def require_thread_scope(
    scope: ScopedProject,
    projects: Annotated[ProjectDirectory, Depends(get_project_directory)],
    thread_id: Annotated[ThreadId, Path()],
) -> ProjectScope:
    """Verify that the thread belongs to the already verified project.

    Raises:
        ApiError: If the thread is not part of this project.
    """
    if not await projects.thread_belongs_to_project(
        project_id=scope.project_id, thread_id=thread_id
    ):
        raise ApiError(ErrorCode.NOT_FOUND, "thread not found")
    return ProjectScope(
        tenant_id=scope.tenant_id,
        user_id=scope.user_id,
        project_id=scope.project_id,
        thread_id=thread_id,
    )


ScopedThread = Annotated[ProjectScope, Depends(require_thread_scope)]
