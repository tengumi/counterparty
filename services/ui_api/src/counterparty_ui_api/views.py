"""Turning stored rows into the public DTOs of the REST contract.

The DTOs are the contract; this module is the only place that decides how a
row becomes one, so two endpoints cannot disagree about what a project looks
like. Nothing is invented here: a field the workspace does not hold yet is
absent rather than defaulted to something reassuring.
"""

from counterparty_contracts import (
    Page,
    PageInfo,
    Project,
    ProjectId,
    ThreadId,
    WorkflowStatus,
)
from counterparty_storage.workspace.models import Project as ProjectRow

from .reads import ProjectDetails

__all__ = ["as_page", "as_project"]


def as_project(row: ProjectRow, details: ProjectDetails) -> Project:
    """Render one stored project as the public DTO.

    ``last_open_question``, ``latest_artifact`` and ``latest_decision`` stay
    absent: the conversation projection, artifacts and decisions are not part
    of this service's storage yet, and an absent value is honest where an
    empty one would read as "there is none".

    Raises:
        ValueError: If the project has no default chat. Every project is
            created with its first one, so this is a broken row rather than a
            state a caller can reach.
    """
    if row.default_thread_id is None:
        raise ValueError(f"project {row.id} has no default thread")
    return Project(
        id=ProjectId(row.id),
        title=row.title,
        default_thread_id=ThreadId(row.default_thread_id),
        threads_count=details.threads_count,
        context_version=row.context_version,
        workflow_status=WorkflowStatus(row.workflow_status.value),
        created_at=row.created_at,
        updated_at=row.updated_at,
        companies=details.companies,
    )


def as_page[ItemT](items: list[ItemT], *, limit: int, next_cursor: str | None) -> Page[ItemT]:
    """Wrap items in the shared page envelope.

    ``has_more`` follows the cursor: a page is the last one exactly when the
    server has no position to continue from, so an empty page never has to be
    read as proof that a collection is exhausted.
    """
    return Page[ItemT](
        items=items,
        page=PageInfo(limit=limit, next_cursor=next_cursor, has_more=next_cursor is not None),
    )
