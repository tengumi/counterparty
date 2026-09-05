"""Durable run lifecycle behind the in-memory transport registry (AG-04).

The V01 registry keeps the replayable event log in memory so that leaving the
page stops the subscription, not the run. AG-04 adds the part that must survive
the process: the run's *lifecycle* — accepted, running, cancelling, and its
terminal state — is written to ``workspace.agent_runs`` through the single
fenced :class:`~counterparty_storage.repositories.AgentRunOwner` connection.

What this does not persist is the message and activity projection. Replaying a
lost token is explicitly not required (Specs 10 §7); what a reconnect after a
restart gets is the durable lifecycle, and an interrupted run reads as
interrupted rather than as forever running.

Every method fails soft: a lifecycle mirror that cannot be written is logged
and the in-memory run continues. The one exception is :meth:`accept`, whose
failure the caller turns into a refusal, because the database is where "one
active run per thread" is enforced.
"""

import logging
from uuid import UUID

from counterparty_contracts import ProjectId, RunId, RunInfo, RunStatus, ThreadId
from counterparty_storage import NotFoundError, ThreadScope
from counterparty_storage.repositories import AgentRunOwner
from counterparty_storage.workspace import AgentRunStatus
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

_TERMINAL: frozenset[RunStatus] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.AWAITING_INPUT,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.INTERRUPTED,
    }
)


class ActiveRunExists(Exception):
    """The thread already has a run that has not finished."""


class DurableRuns:
    """Mirror of run lifecycle onto ``workspace.agent_runs``."""

    def __init__(self, owner: AgentRunOwner) -> None:
        """Bind to the process's single fenced run owner."""
        self._owner = owner

    async def resolve_scope(self, *, project_id: UUID, thread_id: UUID) -> ThreadScope | None:
        """Trusted ``(tenant, project, thread)`` for an RPC that has no session."""
        return await self._owner.resolve_thread_scope(project_id=project_id, thread_id=thread_id)

    async def accept(
        self,
        scope: ThreadScope,
        *,
        run_id: RunId,
        client_request_id: UUID,
        based_on_context_version: int,
    ) -> None:
        """Record acceptance before the run starts.

        Raises:
            ActiveRunExists: If the thread already holds an unfinished run; the
                partial unique index on ``agent_runs`` is what rejects it.
        """
        try:
            async with self._owner.runs(scope) as repository:
                await repository.create(
                    run_id=UUID(str(run_id)),
                    client_request_id=client_request_id,
                    based_on_context_version=based_on_context_version,
                )
        except IntegrityError as error:
            raise ActiveRunExists(str(run_id)) from error

    async def advance(self, scope: ThreadScope, run_id: RunId, status: RunStatus) -> None:
        """Mirror one lifecycle transition; a failure here never stops the run."""
        try:
            async with self._owner.runs(scope) as repository:
                await repository.set_status(UUID(str(run_id)), _storage_status(status))
        except (NotFoundError, ValueError, IntegrityError) as error:
            logger.warning("Run %s lifecycle mirror to %s skipped: %s", run_id, status, error)
        except Exception:
            logger.exception("Run %s lifecycle mirror to %s failed", run_id, status)

    async def lookup(self, run_id: RunId) -> RunInfo | None:
        """Return the durable lifecycle of a run this process did not start."""
        row = await self._owner.find_run(UUID(str(run_id)))
        if row is None:
            return None
        return RunInfo(
            id=RunId(row.id),
            thread_id=ThreadId(row.thread_id),
            project_id=ProjectId(row.project_id),
            status=RunStatus(row.status.value),
            started_at=row.started_at,
            finished_at=row.finished_at,
            based_on_context_version=row.based_on_context_version,
            last_public_revision=row.last_public_revision,
        )


def _storage_status(status: RunStatus) -> AgentRunStatus:
    """Map the public run status onto the storage enum by value."""
    return AgentRunStatus(status.value)


def is_terminal(status: RunStatus) -> bool:
    """Whether no further lifecycle transition is expected for this status."""
    return status in _TERMINAL
