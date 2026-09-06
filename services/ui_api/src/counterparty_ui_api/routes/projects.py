"""Project endpoints: create, list, open and rename a counterparty check.

Four rules of this file are worth stating once, because the handlers below are
short precisely because they hold:

* creating a check creates its first chat in the same transaction. A project
  without a chat is never observable, and the UI does not have to make a second
  call to become usable.
* creating a check runs no model. The first message is sent to the agent
  service afterwards; here it only names the check.
* a repeated ``client_request_id`` never creates a second project. What the
  repeat gets is decided in :mod:`.idempotency` by the reservation table.
* renaming changes the title and nothing else. It does not advance
  ``context_version``, so an AI conclusion does not become outdated because the
  user tidied up a name.
"""

from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    CreateProjectRequest,
    ErrorCode,
    Page,
    Project,
    UpdateProjectRequest,
)
from counterparty_storage import AsyncUnitOfWork
from fastapi import APIRouter, Query, Response, status

from ..cursors import decode_cursor, encode_cursor
from ..dependencies import CurrentSession, ScopedProject, TenantWork
from ..errors import ApiError
from ..idempotency import fingerprint_of, release_reservation, reserve_or_answer
from ..reads import as_page, as_project, load_project_details

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

CREATE_SCOPE = "projects.create"
"""Operation the request id is reserved for. The same id used for another
operation is a different reservation, not a duplicate of this one."""

REPLAY_HEADER = "idempotent-replay"
"""Set on the response that returns an already created project again."""

_DEFAULT_TITLE = "Новая проверка"
_TITLE_FROM_QUESTION_LIMIT = 80


def _title_of(request: CreateProjectRequest) -> str:
    """Choose the title of a new check.

    The first question is used as the name when the user did not give one; it
    is what they would recognize the check by. It is shortened rather than
    reworded, so the title stays their own words.
    """
    if request.title is not None:
        return request.title
    if request.initial_question is not None:
        question = request.initial_question.strip()
        if len(question) > _TITLE_FROM_QUESTION_LIMIT:
            return question[: _TITLE_FROM_QUESTION_LIMIT - 1].rstrip() + "…"
        return question
    return _DEFAULT_TITLE


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: CreateProjectRequest,
    response: Response,
    session: CurrentSession,
    uow: TenantWork,
) -> Project:
    """Start one counterparty check together with its first chat.

    A repeat of the same ``client_request_id`` returns the project the first
    attempt created, answered ``200`` instead of ``201`` and marked with the
    ``idempotent-replay`` header, so a client can tell a replay from a create.

    Raises:
        ApiError: If an identical request is still running, if the request id
            was used for a different payload, or if the created project can no
            longer be read back.
    """
    fingerprint = fingerprint_of(
        {
            "title": payload.title,
            "initial_question": payload.initial_question,
            "owner": str(session.user_id),
        }
    )
    request_id = UUID(str(payload.client_request_id))
    reservation = await reserve_or_answer(
        uow,
        scope=CREATE_SCOPE,
        client_request_id=request_id,
        fingerprint=fingerprint,
        resource_kind="project",
    )
    if reservation.resource_id is not None:
        response.status_code = status.HTTP_200_OK
        response.headers[REPLAY_HEADER] = "true"
        return await _read_project(uow, reservation.resource_id)

    title = _title_of(payload)
    try:
        project = await uow.projects.create(owner_id=UUID(str(session.user_id)), title=title)
        thread = await uow.threads.create(uow.scope.project(project.id), title=title)
        await uow.projects.set_default_thread(project.id, thread.id)
        await uow.idempotency.complete(
            scope=CREATE_SCOPE, client_request_id=request_id, resource_id=project.id
        )
        await uow.commit()
    except Exception:
        await release_reservation(uow, scope=CREATE_SCOPE, client_request_id=request_id)
        raise
    return await _read_project(uow, project.id)


@router.get("", response_model=Page[Project])
async def list_projects(
    session: CurrentSession,
    uow: TenantWork,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> Page[Project]:
    """List the caller's checks, most recently active first.

    ``query`` matches a literal title substring, ignoring case.
    Only the caller's own checks are listed: a project that could not be
    opened must not appear in the list that offers to open it.

    The page is read one row wider than requested, so ``has_more`` reports what
    the collection holds rather than what this page happened to contain.
    """
    position = decode_cursor(cursor) if cursor is not None else None
    rows = await uow.projects.list_recent(
        owner_id=UUID(str(session.user_id)),
        title_contains=query,
        limit=limit + 1,
        updated_before=None if position is None else position.instant,
        before_id=None if position is None else position.row_id,
    )
    page = rows[:limit]
    details = await load_project_details(uow, [row.id for row in page])
    next_cursor = (
        encode_cursor(page[-1].updated_at, page[-1].id) if len(rows) > limit and page else None
    )
    return as_page(
        [as_project(row, details[row.id]) for row in page], limit=limit, next_cursor=next_cursor
    )


@router.get("/{project_id}", response_model=Project)
async def open_project(scope: ScopedProject, uow: TenantWork) -> Project:
    """Open one check the caller owns."""
    return await _read_project(uow, UUID(str(scope.project_id)))


@router.patch("/{project_id}", response_model=Project)
async def rename_project(
    payload: UpdateProjectRequest, scope: ScopedProject, uow: TenantWork
) -> Project:
    """Rename one check.

    The deal context is untouched: ``context_version`` does not move, so no
    conclusion drawn from the previous context becomes outdated.
    """
    project_id = UUID(str(scope.project_id))
    await uow.projects.rename(project_id, payload.title)
    await uow.commit()
    return await _read_project(uow, project_id)


async def _read_project(uow: AsyncUnitOfWork, project_id: UUID) -> Project:
    """Read one project of this tenant back as the public DTO.

    Raises:
        ApiError: If the project is not readable by this caller.
    """
    row = await uow.projects.get(project_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "project not found")
    details = await load_project_details(uow, [project_id])
    return as_project(row, details[project_id])
