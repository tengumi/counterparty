"""Tenant-scoped repositories over the ``workspace`` schema.

Every statement in this module is filtered by the tenant of the scope the
repository was built with, and a child row is reached through its project, so
one tenant's project, chat or counterparty is not merely hidden from another
tenant — it is not addressable from another tenant's repository at all. The
composite foreign keys in the schema make the same statement one layer down, so
a query written by hand cannot cross the boundary either.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import ProjectScope, TenantScope
from ..errors import (
    ContextVersionConflictError,
    IdempotencyConflictError,
    NotFoundError,
    ProjectCompanyLimitError,
    ProjectDeletedError,
)
from ..workspace.enums import CounterpartyRole, IdempotencyState, ThreadStatus, WorkflowStatus
from ..workspace.models import (
    MAX_PROJECT_COMPANIES,
    IdempotencyKey,
    Project,
    ProjectCompany,
    Thread,
)

__all__ = [
    "CompanyAddition",
    "IdempotencyRepository",
    "ProjectCompanyRepository",
    "ProjectRepository",
    "Reservation",
    "ReservationOutcome",
    "ThreadRepository",
]


#: Every timestamp this module writes comes from the database clock, not from
#: the process clock: a skewed application host must not be able to record a
#: deletion that happened "before" the row was created.
_DB_NOW = func.clock_timestamp()


class _TenantScoped:
    """Base holding the session and the scope every statement is filtered by."""

    def __init__(self, session: AsyncSession, scope: TenantScope) -> None:
        """Bind the repository to one session and one tenant."""
        self._session = session
        self._scope = scope

    @property
    def tenant_id(self) -> UUID:
        """Tenant every statement of this repository is restricted to."""
        return self._scope.tenant_id

    def _assert_same_tenant(self, scope: ProjectScope) -> None:
        """Refuse a project scope that was built for another tenant.

        Raises:
            ValueError: If the scopes disagree. This is a programming error,
                not a permission answer, so it is not reported as "not found".
        """
        if scope.tenant_id != self.tenant_id:
            raise ValueError("project scope belongs to a different tenant")


class ProjectRepository(_TenantScoped):
    """Counterparty checks of one tenant."""

    def _visible(self, *, include_deleted: bool = False) -> Select[tuple[Project]]:
        statement = select(Project).where(Project.tenant_id == self.tenant_id)
        if not include_deleted:
            statement = statement.where(Project.deleted_at.is_(None))
        return statement

    async def create(
        self,
        *,
        owner_id: UUID,
        title: str,
        project_id: UUID | None = None,
    ) -> Project:
        """Start one check. This creates no chat and no agent run by itself."""
        project = Project(
            id=project_id or uuid4(),
            tenant_id=self.tenant_id,
            owner_id=owner_id,
            title=title,
            context_version=0,
            workflow_status=WorkflowStatus.IN_PROGRESS,
        )
        self._session.add(project)
        await self._session.flush()
        return project

    async def get(self, project_id: UUID, *, include_deleted: bool = False) -> Project | None:
        """Return the project, or ``None`` when this tenant does not hold it."""
        statement = self._visible(include_deleted=include_deleted).where(Project.id == project_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def require(self, project_id: UUID) -> Project:
        """Return the project or refuse.

        Raises:
            NotFoundError: If this tenant has no such project.
        """
        project = await self.get(project_id)
        if project is None:
            raise NotFoundError("project", project_id)
        return project

    async def require_writable(self, project_id: UUID) -> Project:
        """Return the project only while it still accepts writes.

        Raises:
            NotFoundError: If this tenant has no such project.
            ProjectDeletedError: If the project is deleted. Access closes when
                deletion is accepted, not when the cleanup finishes.
        """
        project = await self.get(project_id, include_deleted=True)
        if project is None:
            raise NotFoundError("project", project_id)
        if project.deleted_at is not None:
            raise ProjectDeletedError(project_id)
        return project

    async def list_recent(
        self,
        *,
        limit: int,
        updated_before: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Project]:
        """Return the tenant's projects, most recently active first.

        The cursor is the pair ``(updated_at, id)`` so that projects touched in
        the same instant are still paged through exactly once.
        """
        statement = self._visible().order_by(Project.updated_at.desc(), Project.id.desc())
        if updated_before is not None:
            keyset = Project.updated_at < updated_before
            if before_id is not None:
                keyset = keyset | and_(Project.updated_at == updated_before, Project.id < before_id)
            statement = statement.where(keyset)
        result = await self._session.execute(statement.limit(limit))
        return list(result.scalars())

    async def rename(self, project_id: UUID, title: str) -> Project:
        """Rename a project.

        A rename is not a change of the deal context, so it does not advance
        ``context_version`` and does not make an AI conclusion outdated.
        """
        project = await self.require_writable(project_id)
        project.title = title
        await self._session.flush()
        return project

    async def set_workflow_status(self, project_id: UUID, status: WorkflowStatus) -> Project:
        """Record where the check stands. This is not a risk assessment."""
        project = await self.require_writable(project_id)
        project.workflow_status = status
        await self._session.flush()
        return project

    async def set_default_thread(self, project_id: UUID, thread_id: UUID | None) -> Project:
        """Point the project at the chat that opens by default."""
        project = await self.require_writable(project_id)
        project.default_thread_id = thread_id
        await self._session.flush()
        return project

    async def bump_context_version(self, project_id: UUID, *, expected: int) -> int:
        """Advance the deal context under the version the caller last saw.

        Raises:
            ContextVersionConflictError: If the context moved meanwhile; the
                caller re-reads instead of overwriting someone else's change.
        """
        project = await self.require_writable(project_id)
        statement = (
            update(Project)
            .where(
                Project.id == project_id,
                Project.tenant_id == self.tenant_id,
                Project.deleted_at.is_(None),
                Project.context_version == expected,
            )
            .values(context_version=Project.context_version + 1, updated_at=func.clock_timestamp())
            .returning(Project.context_version)
        )
        updated = (await self._session.execute(statement)).scalar_one_or_none()
        if updated is None:
            await self._session.refresh(project)
            raise ContextVersionConflictError(project_id, expected, project.context_version)
        await self._session.refresh(project)
        return updated

    async def soft_delete(
        self, project_id: UUID, *, expected_version: int | None = None
    ) -> Project:
        """Close access to the project.

        The row stays until the asynchronous cleanup of its files, projections
        and checkpoints has run, but writes stop immediately.

        Raises:
            ContextVersionConflictError: If the caller guarded the deletion
                with a version and the context has moved since.
        """
        project = await self.require_writable(project_id)
        if expected_version is not None and project.context_version != expected_version:
            raise ContextVersionConflictError(project_id, expected_version, project.context_version)
        statement = (
            update(Project)
            .where(Project.id == project_id, Project.tenant_id == self.tenant_id)
            .values(deleted_at=_DB_NOW, updated_at=_DB_NOW)
            .returning(Project)
        )
        return (await self._session.execute(statement)).scalar_one()


class ThreadRepository(_TenantScoped):
    """Chats inside the projects of one tenant."""

    def _visible(self) -> Select[tuple[Thread]]:
        return (
            select(Thread)
            .join(Project, Project.id == Thread.project_id)
            .where(Thread.tenant_id == self.tenant_id, Project.deleted_at.is_(None))
        )

    async def create(
        self, scope: ProjectScope, *, title: str, thread_id: UUID | None = None
    ) -> Thread:
        """Open another chat in the project. Terms and documents stay shared.

        Raises:
            ValueError: If the project scope belongs to a different tenant.
        """
        self._assert_same_tenant(scope)
        thread = Thread(
            id=thread_id or uuid4(),
            project_id=scope.project_id,
            tenant_id=self.tenant_id,
            title=title,
            status=ThreadStatus.ACTIVE,
        )
        self._session.add(thread)
        await self._session.flush()
        return thread

    async def get(self, thread_id: UUID) -> Thread | None:
        """Return one chat of this tenant, or ``None``."""
        statement = self._visible().where(Thread.id == thread_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def require(self, thread_id: UUID) -> Thread:
        """Return one chat or refuse.

        Raises:
            NotFoundError: If this tenant has no such chat.
        """
        thread = await self.get(thread_id)
        if thread is None:
            raise NotFoundError("thread", thread_id)
        return thread

    async def list_for_project(self, scope: ProjectScope, *, limit: int = 50) -> list[Thread]:
        """Return the chats of one project, most recently active first."""
        self._assert_same_tenant(scope)
        statement = (
            self._visible()
            .where(Thread.project_id == scope.project_id)
            .order_by(Thread.last_activity_at.desc(), Thread.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(statement)).scalars())

    async def touch(self, thread_id: UUID) -> Thread:
        """Record that something happened in the chat."""
        await self.require(thread_id)
        statement = (
            update(Thread)
            .where(Thread.id == thread_id, Thread.tenant_id == self.tenant_id)
            .values(last_activity_at=_DB_NOW)
            .returning(Thread)
        )
        return (await self._session.execute(statement)).scalar_one()

    async def set_archived(self, thread_id: UUID, *, archived: bool) -> Thread:
        """Archive or restore one chat.

        Archiving never cancels a run on its own; the UI confirms that first.
        """
        await self.require(thread_id)
        statement = (
            update(Thread)
            .where(Thread.id == thread_id, Thread.tenant_id == self.tenant_id)
            .values(
                status=ThreadStatus.ARCHIVED if archived else ThreadStatus.ACTIVE,
                archived_at=_DB_NOW if archived else None,
            )
            .returning(Thread)
        )
        return (await self._session.execute(statement)).scalar_one()


@dataclass(frozen=True, slots=True)
class CompanyAddition:
    """Outcome of adding one counterparty to a project."""

    company: ProjectCompany
    created: bool
    """``False`` when the counterparty was already in the active composition;
    the request succeeded without adding a duplicate."""


class ProjectCompanyRepository(_TenantScoped):
    """The counterparties currently under review inside a project."""

    async def list_active(self, scope: ProjectScope) -> list[ProjectCompany]:
        """Return the current composition, in slot order."""
        self._assert_same_tenant(scope)
        statement = (
            select(ProjectCompany)
            .where(
                ProjectCompany.tenant_id == self.tenant_id,
                ProjectCompany.project_id == scope.project_id,
                ProjectCompany.removed_at.is_(None),
            )
            .order_by(ProjectCompany.slot)
        )
        return list((await self._session.execute(statement)).scalars())

    async def add(
        self,
        scope: ProjectScope,
        *,
        company_id: UUID,
        report_id: UUID,
        role: CounterpartyRole = CounterpartyRole.UNKNOWN,
        shortlisted: bool = False,
    ) -> CompanyAddition:
        """Add one counterparty, pinned to the snapshot it will be judged on.

        Raises:
            ProjectCompanyLimitError: If all twenty slots are taken. The
                database refuses the twenty-first row as well; this check only
                turns the refusal into a per-item answer instead of an abort.
        """
        self._assert_same_tenant(scope)
        active = await self.list_active(scope)
        for existing in active:
            if existing.company_id == company_id:
                return CompanyAddition(company=existing, created=False)
        taken = {row.slot for row in active}
        free = next(
            (slot for slot in range(1, MAX_PROJECT_COMPANIES + 1) if slot not in taken), None
        )
        if free is None:
            raise ProjectCompanyLimitError(scope.project_id, MAX_PROJECT_COMPANIES)
        added = ProjectCompany(
            id=uuid4(),
            project_id=scope.project_id,
            tenant_id=self.tenant_id,
            company_id=company_id,
            report_id=report_id,
            slot=free,
            role=role,
            shortlisted=shortlisted,
        )
        self._session.add(added)
        await self._session.flush()
        return CompanyAddition(company=added, created=True)

    async def remove(self, scope: ProjectScope, *, company_id: UUID) -> ProjectCompany:
        """Take one counterparty out of the active composition.

        The row and its pinned ``report_id`` are kept: what was reviewed stays
        answerable after the counterparty leaves the comparison, and the source
        snapshot is never deleted by this.

        Raises:
            NotFoundError: If the counterparty is not in the composition.
        """
        self._assert_same_tenant(scope)
        statement = (
            update(ProjectCompany)
            .where(
                ProjectCompany.tenant_id == self.tenant_id,
                ProjectCompany.project_id == scope.project_id,
                ProjectCompany.company_id == company_id,
                ProjectCompany.removed_at.is_(None),
            )
            .values(removed_at=func.now())
            .returning(ProjectCompany)
        )
        removed = (await self._session.execute(statement)).scalar_one_or_none()
        if removed is None:
            raise NotFoundError("project company", company_id)
        return removed


class ReservationOutcome(StrEnum):
    """What a repeated request id meant."""

    STARTED = "started"
    """First time this id was seen; the caller does the work."""

    IN_FLIGHT = "in_flight"
    """An identical request is still running; the caller waits instead of
    starting a second copy of it."""

    REPLAYED = "replayed"
    """The identical request already finished; its result is returned again."""


@dataclass(frozen=True, slots=True)
class Reservation:
    """One reserved request id and what the caller should do with it."""

    outcome: ReservationOutcome
    key: IdempotencyKey

    @property
    def resource_id(self) -> UUID | None:
        """Identity of what the first attempt created, once it finished."""
        return self.key.resource_id


class IdempotencyRepository(_TenantScoped):
    """Reservations that make a repeated write harmless.

    The guarantee is the primary key ``(tenant_id, scope, client_request_id)``,
    not a check performed here: two concurrent copies of the same request race
    for one row and exactly one of them wins.
    """

    async def reserve(
        self,
        *,
        scope: str,
        client_request_id: UUID,
        request_fingerprint: str,
        resource_kind: str,
    ) -> Reservation:
        """Claim the request id, or report what the first attempt did with it.

        Raises:
            IdempotencyConflictError: If the id was already used for a
                different payload. Replaying the first resource would discard
                this request without telling anyone.
        """
        statement = (
            insert(IdempotencyKey)
            .values(
                tenant_id=self.tenant_id,
                scope=scope,
                client_request_id=client_request_id,
                request_fingerprint=request_fingerprint,
                state=IdempotencyState.IN_FLIGHT,
                resource_kind=resource_kind,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyKey.tenant_id,
                    IdempotencyKey.scope,
                    IdempotencyKey.client_request_id,
                ]
            )
            .returning(IdempotencyKey)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return Reservation(outcome=ReservationOutcome.STARTED, key=inserted)

        existing = await self._require_key(scope, client_request_id)
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(scope, client_request_id)
        if existing.state is IdempotencyState.COMPLETED:
            return Reservation(outcome=ReservationOutcome.REPLAYED, key=existing)
        return Reservation(outcome=ReservationOutcome.IN_FLIGHT, key=existing)

    async def complete(
        self,
        *,
        scope: str,
        client_request_id: UUID,
        resource_id: UUID,
        response: dict[str, Any] | None = None,
    ) -> IdempotencyKey:
        """Attach the created resource to the reservation.

        This runs in the same transaction as the write it describes, so a
        completed reservation cannot name a resource that was rolled back.
        """
        await self._require_key(scope, client_request_id)
        statement = (
            update(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == self.tenant_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.client_request_id == client_request_id,
            )
            .values(
                state=IdempotencyState.COMPLETED,
                resource_id=resource_id,
                response_jsonb=response,
                completed_at=_DB_NOW,
            )
            .returning(IdempotencyKey)
        )
        return (await self._session.execute(statement)).scalar_one()

    async def _require_key(self, scope: str, client_request_id: UUID) -> IdempotencyKey:
        statement = select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == self.tenant_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.client_request_id == client_request_id,
        )
        key = (await self._session.execute(statement)).scalar_one_or_none()
        if key is None:
            raise NotFoundError("idempotency key", client_request_id)
        return key
