"""One transaction, one tenant, one set of repositories.

A unit of work owns the transaction boundary so a caller never half-applies a
change: adding a counterparty, advancing the context version and completing the
idempotency reservation either all land or none of them do.

Two properties are deliberate:

* nothing commits by itself. Leaving the block without calling :meth:`commit`
  rolls back, so an unfinished handler cannot leave a partial project behind.
* every workspace repository is built from the same :class:`TenantScope`, so a
  unit of work cannot mix two tenants in one transaction even by accident.

Importing this module opens nothing. An engine is created by the service that
owns its configuration, at startup, not here.
"""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from .access import TenantScope
from .repositories import (
    AgentRunReadRepository,
    AnalysisArtifactRepository,
    CompanyReadRepository,
    IdempotencyRepository,
    ProjectCompanyRepository,
    ProjectRepository,
    ReportSnapshotReadRepository,
    ThreadRepository,
    UserDecisionRepository,
)

__all__ = ["AsyncUnitOfWork"]


class AsyncUnitOfWork:
    """Repositories of one tenant, sharing one transaction."""

    def __init__(self, session: AsyncSession, scope: TenantScope) -> None:
        """Build every repository of this transaction for one tenant."""
        self._session = session
        self._scope = scope
        self.projects = ProjectRepository(session, scope)
        self.threads = ThreadRepository(session, scope)
        self.project_companies = ProjectCompanyRepository(session, scope)
        self.idempotency = IdempotencyRepository(session, scope)
        self.decisions = UserDecisionRepository(session, scope)
        self.artifacts = AnalysisArtifactRepository(session, scope)
        self.agent_runs = AgentRunReadRepository(session, scope)
        """Read-only run lifecycle for the UI; the agent writes runs elsewhere."""

        self.companies = CompanyReadRepository(session)
        """The shared report corpus, read-only: workspace work never edits it."""

        self.report_snapshots = ReportSnapshotReadRepository(session)

    @property
    def scope(self) -> TenantScope:
        """Tenant and caller every repository here is bound to."""
        return self._scope

    @property
    def session(self) -> AsyncSession:
        """The underlying session, for a statement no repository covers yet."""
        return self._session

    async def __aenter__(self) -> Self:
        """Enter the transaction boundary."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back unless the caller committed explicitly."""
        await self._session.rollback()

    async def flush(self) -> None:
        """Send pending changes so the database checks them now."""
        await self._session.flush()

    async def commit(self) -> None:
        """Make everything in this unit of work durable, all together."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Discard everything in this unit of work."""
        await self._session.rollback()
