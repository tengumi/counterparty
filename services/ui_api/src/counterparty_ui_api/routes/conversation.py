"""The stored public projection of one chat, read when it opens.

Opening a project reads this over REST before it subscribes to a run that is
still active (Specs 06 §3, 10 §5). This service does not hold the message and
activity projection — that is the agent service's durable state — so the
projection returned here carries an empty history and the run lifecycle the UI
can reconnect to. It never invents messages: an empty history means the chat is
empty, not that a load failed.
"""

from uuid import UUID

from counterparty_contracts import ErrorCode, ThreadConversationState, ThreadId
from fastapi import APIRouter

from ..dependencies import ScopedThread, TenantWork
from ..errors import ApiError
from ..reads import as_thread_conversation

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/projects", tags=["conversation"])


@router.get(
    "/{project_id}/threads/{thread_id}/conversation",
    response_model=ThreadConversationState,
)
async def get_thread_conversation(scope: ScopedThread, uow: TenantWork) -> ThreadConversationState:
    """Return the stored projection of one chat plus its active run, if any."""
    assert scope.thread_id is not None  # guaranteed by ScopedThread
    project_id = UUID(str(scope.project_id))
    thread_id = UUID(str(scope.thread_id))
    project = await uow.projects.get(project_id)
    if project is None:
        raise ApiError(ErrorCode.NOT_FOUND, "project not found")
    project_scope = uow.scope.project(project_id)
    run = await uow.agent_runs.latest_for_thread(project_scope, thread_id)
    # The newest run's projection may still be unwritten while it works; fall
    # back to the last one that has a projection so the history is not lost.
    projection_run = run
    if run is not None and run.public_projection is None:
        projection_run = await uow.agent_runs.latest_projection_for_thread(project_scope, thread_id)
    return as_thread_conversation(project, ThreadId(thread_id), run, projection_run)
