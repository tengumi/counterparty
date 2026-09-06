"""Tenant-scoped repositories over the ``workspace`` schema.

Every statement in this module is filtered by the tenant of the scope the
repository was built with, and a child row is reached through its project, so
one tenant's project, chat or counterparty is not merely hidden from another
tenant — it is not addressable from another tenant's repository at all. The
composite foreign keys in the schema make the same statement one layer down, so
a query written by hand cannot cross the boundary either.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from ..access import ProjectScope, TenantScope, ThreadScope
from ..errors import (
    ContextVersionConflictError,
    IdempotencyConflictError,
    NotFoundError,
    ProjectCompanyLimitError,
    ProjectDeletedError,
)
from ..reports.models import Company, CompanyProfile
from ..workspace.enums import (
    AgentRunStatus,
    ArtifactFreshness,
    CounterpartyRole,
    DecisionOutcome,
    IdempotencyState,
    ThreadStatus,
    WorkflowStatus,
)
from ..workspace.models import (
    MAX_PROJECT_COMPANIES,
    AgentRun,
    AnalysisArtifact,
    IdempotencyKey,
    Project,
    ProjectCompany,
    Thread,
    UserDecision,
)

__all__ = [
    "AgentRunReadRepository",
    "AnalysisArtifactRepository",
    "CompanyAddition",
    "IdempotencyRepository",
    "ProjectCompanyRecord",
    "ProjectCompanyRepository",
    "ProjectRepository",
    "Reservation",
    "ReservationOutcome",
    "ThreadRepository",
    "UserDecisionRepository",
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
        owner_id: UUID | None = None,
        title_contains: str | None = None,
        updated_before: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Project]:
        """Return the tenant's projects, most recently active first.

        The cursor is the pair ``(updated_at, id)`` so that projects touched in
        the same instant are still paged through exactly once.
        """
        statement = self._visible().order_by(Project.updated_at.desc(), Project.id.desc())
        if owner_id is not None:
            statement = statement.where(Project.owner_id == owner_id)
        if title_contains is not None:
            statement = statement.where(Project.title.icontains(title_contains, autoescape=True))
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


class UserDecisionRepository(_TenantScoped):
    """Decisions a person recorded inside the projects of one tenant.

    A decision is independent of any AI artifact and is never overwritten:
    revising one inserts a new row that points back with ``supersedes_id``.
    """

    async def list_for_project(self, scope: ProjectScope) -> list[UserDecision]:
        """Return the project's decisions, newest first."""
        self._assert_same_tenant(scope)
        statement = (
            select(UserDecision)
            .where(
                UserDecision.tenant_id == self.tenant_id,
                UserDecision.project_id == scope.project_id,
            )
            .order_by(UserDecision.created_at.desc(), UserDecision.id.desc())
        )
        return list((await self._session.execute(statement)).scalars())

    async def get(self, scope: ProjectScope, decision_id: UUID) -> UserDecision | None:
        """Return one decision of this project, or ``None``."""
        self._assert_same_tenant(scope)
        statement = select(UserDecision).where(
            UserDecision.tenant_id == self.tenant_id,
            UserDecision.project_id == scope.project_id,
            UserDecision.id == decision_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def record(
        self,
        scope: ProjectScope,
        *,
        author_user_id: UUID,
        outcome: DecisionOutcome,
        rationale: str,
        conditions: Sequence[str],
        company_ids: Sequence[UUID],
        context_version: int,
        evidence_refs: Sequence[str],
        based_on_artifact_id: UUID | None = None,
        based_on_artifact_version: int | None = None,
        supersedes_id: UUID | None = None,
    ) -> UserDecision:
        """Insert one decision. The author is the caller, not a body field.

        The project must still accept writes; the identifiers are stored as
        given, so a decision may name a counterparty that has since left the
        composition.
        """
        self._assert_same_tenant(scope)
        await ProjectRepository(self._session, TenantScope(self.tenant_id)).require_writable(
            scope.project_id
        )
        decision = UserDecision(
            id=uuid4(),
            tenant_id=self.tenant_id,
            project_id=scope.project_id,
            outcome=outcome,
            company_ids=[str(company_id) for company_id in company_ids],
            rationale=rationale,
            conditions=list(conditions),
            based_on_artifact_id=based_on_artifact_id,
            based_on_artifact_version=based_on_artifact_version,
            context_version=context_version,
            evidence_refs=list(evidence_refs),
            author_user_id=author_user_id,
            supersedes_id=supersedes_id,
        )
        self._session.add(decision)
        await self._session.flush()
        return decision


class AnalysisArtifactRepository(_TenantScoped):
    """Immutable AI conclusions stored per project of one tenant.

    Nothing in this service writes them yet; the agent creates them once it can
    reason for a project. Reads are here so the product can show them the moment
    they exist.
    """

    async def list_for_project(
        self, scope: ProjectScope, *, latest_only: bool = False
    ) -> list[AnalysisArtifact]:
        """Return the project's artifacts, newest first.

        With ``latest_only`` only the highest ``version`` of each artifact id is
        returned, which is what the UI shows by default.
        """
        self._assert_same_tenant(scope)
        statement = select(AnalysisArtifact).where(
            AnalysisArtifact.tenant_id == self.tenant_id,
            AnalysisArtifact.project_id == scope.project_id,
        )
        if latest_only:
            statement = statement.distinct(AnalysisArtifact.id).order_by(
                AnalysisArtifact.id, AnalysisArtifact.version.desc()
            )
            rows = list((await self._session.execute(statement)).scalars())
            rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
            return rows
        statement = statement.order_by(
            AnalysisArtifact.created_at.desc(),
            AnalysisArtifact.id.desc(),
            AnalysisArtifact.version.desc(),
        )
        return list((await self._session.execute(statement)).scalars())

    async def get_version(
        self, scope: ProjectScope, *, artifact_id: UUID, version: int
    ) -> AnalysisArtifact | None:
        """Return one immutable artifact version of this project, or ``None``."""
        self._assert_same_tenant(scope)
        statement = select(AnalysisArtifact).where(
            AnalysisArtifact.tenant_id == self.tenant_id,
            AnalysisArtifact.project_id == scope.project_id,
            AnalysisArtifact.id == artifact_id,
            AnalysisArtifact.version == version,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def add_version(
        self,
        scope: ProjectScope,
        *,
        artifact_id: UUID,
        version: int,
        based_on_context_version: int,
        question: str,
        summary: str,
        freshness: ArtifactFreshness = ArtifactFreshness.CURRENT,
        report_ids: Sequence[UUID] = (),
        grounds: Sequence[dict[str, Any]] = (),
        unknowns: Sequence[str] = (),
        next_actions: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        created_by_run_id: UUID | None = None,
        source_thread_id: UUID | None = None,
    ) -> AnalysisArtifact:
        """Insert one immutable artifact version. An existing pair is refused."""
        self._assert_same_tenant(scope)
        await ProjectRepository(self._session, TenantScope(self.tenant_id)).require_writable(
            scope.project_id
        )
        artifact = AnalysisArtifact(
            id=artifact_id,
            version=version,
            tenant_id=self.tenant_id,
            project_id=scope.project_id,
            based_on_context_version=based_on_context_version,
            report_ids=[str(report_id) for report_id in report_ids],
            question=question,
            summary=summary,
            grounds=list(grounds),
            unknowns=list(unknowns),
            next_actions=list(next_actions),
            evidence_refs=list(evidence_refs),
            freshness=freshness,
            created_by_run_id=created_by_run_id,
            source_thread_id=source_thread_id,
        )
        self._session.add(artifact)
        await self._session.flush()
        return artifact


class AgentRunReadRepository(_TenantScoped):
    """Read-only view of run lifecycle for the UI, scoped to one tenant.

    The durable run records are written by the agent process on its own owner
    connection (:class:`AgentRunOwner`). The UI only needs to read the current
    run of a thread to offer a reconnect, so this stays a plain scoped select.
    """

    async def latest_for_thread(self, scope: ProjectScope, thread_id: UUID) -> AgentRun | None:
        """Return the most recent run of one thread of this project, if any."""
        self._assert_same_tenant(scope)
        statement = (
            select(AgentRun)
            .where(
                AgentRun.tenant_id == self.tenant_id,
                AgentRun.project_id == scope.project_id,
                AgentRun.thread_id == thread_id,
            )
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def latest_projection_for_thread(
        self, scope: ProjectScope, thread_id: UUID
    ) -> AgentRun | None:
        """The most recent run of the thread that carries a public projection.

        The agent seeds each run's projection with the thread's prior turns, so
        the newest one with a projection holds the whole history. It can be an
        older row than :meth:`latest_for_thread` when a run is still working
        (its projection is written only at the terminal transition).
        """
        self._assert_same_tenant(scope)
        statement = (
            select(AgentRun)
            .where(
                AgentRun.tenant_id == self.tenant_id,
                AgentRun.project_id == scope.project_id,
                AgentRun.thread_id == thread_id,
                AgentRun.public_projection.is_not(None),
            )
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class CompanyAddition:
    """Outcome of adding one counterparty to a project."""

    company: ProjectCompany
    created: bool
    """``False`` when the counterparty was already in the active composition;
    the request succeeded without adding a duplicate."""


@dataclass(frozen=True, slots=True)
class ProjectCompanyRecord:
    """An active composition row with its pinned report identity details."""

    membership: ProjectCompany
    company: Company
    profile: CompanyProfile | None
    """Profile of the pinned report, never a newer snapshot's profile."""


class ProjectCompanyRepository(_TenantScoped):
    """The counterparties currently under review inside a project."""

    async def has_historical_report(self, scope: ProjectScope, report_id: UUID) -> bool:
        """Keep pinned sources reachable after company removal within a live project."""
        self._assert_same_tenant(scope)
        await ProjectRepository(self._session, TenantScope(self.tenant_id)).require(
            scope.project_id
        )
        statement = (
            select(ProjectCompany.id)
            .where(
                ProjectCompany.tenant_id == self.tenant_id,
                ProjectCompany.project_id == scope.project_id,
                ProjectCompany.report_id == report_id,
            )
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

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

    async def list_active_for_projects(
        self, project_ids: Sequence[UUID]
    ) -> dict[UUID, list[ProjectCompanyRecord]]:
        """Read active compositions for a page of visible projects in one query.

        The mapping contains every requested id, including projects with no
        counterparties and ids not visible to this tenant. Each profile comes
        from the report pinned by the membership, never from a newer snapshot.
        """
        grouped: dict[UUID, list[ProjectCompanyRecord]] = {
            project_id: [] for project_id in project_ids
        }
        if not project_ids:
            return grouped
        statement = (
            select(ProjectCompany, Company, CompanyProfile)
            .join(
                Project,
                and_(
                    Project.id == ProjectCompany.project_id,
                    Project.tenant_id == ProjectCompany.tenant_id,
                ),
            )
            .join(Company, Company.id == ProjectCompany.company_id)
            .outerjoin(CompanyProfile, CompanyProfile.report_id == ProjectCompany.report_id)
            .where(
                ProjectCompany.tenant_id == self.tenant_id,
                ProjectCompany.project_id.in_(project_ids),
                ProjectCompany.removed_at.is_(None),
                Project.deleted_at.is_(None),
            )
            .order_by(ProjectCompany.project_id, ProjectCompany.slot)
        )
        for membership, company, profile in (await self._session.execute(statement)).all():
            grouped[membership.project_id].append(
                ProjectCompanyRecord(
                    membership=membership,
                    company=company,
                    profile=profile,
                )
            )
        return grouped

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
        stale_after: timedelta | None = None,
    ) -> Reservation:
        """Claim the request id, or report what the first attempt did with it.

        An in-flight reservation does not expire by default: elapsed time does
        not prove that its worker stopped. A recovery path may opt into an
        atomic takeover with ``stale_after`` after reconciling worker state.

        Raises:
            IdempotencyConflictError: If the id was already used for a
                different payload. Replaying the first resource would discard
                this request without telling anyone.
            ValueError: If ``stale_after`` is not positive.
        """
        if stale_after is not None and stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
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
        if stale_after is not None:
            takeover = (
                update(IdempotencyKey)
                .where(
                    IdempotencyKey.tenant_id == self.tenant_id,
                    IdempotencyKey.scope == scope,
                    IdempotencyKey.client_request_id == client_request_id,
                    IdempotencyKey.request_fingerprint == request_fingerprint,
                    IdempotencyKey.state == IdempotencyState.IN_FLIGHT,
                    IdempotencyKey.created_at <= _DB_NOW - stale_after,
                )
                .values(created_at=_DB_NOW)
                .returning(IdempotencyKey)
            )
            reclaimed = (await self._session.execute(takeover)).scalar_one_or_none()
            if reclaimed is not None:
                return Reservation(outcome=ReservationOutcome.STARTED, key=reclaimed)
            existing = await self._require_key(scope, client_request_id)
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

    async def release(self, *, scope: str, client_request_id: UUID) -> bool:
        """Delete an unfinished reservation after its work was rolled back.

        Completed reservations are immutable. The caller must roll back the
        failed work before releasing its key; this method only narrows deletion
        to the same tenant, operation, request id, and ``in_flight`` state.
        """
        statement = (
            delete(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == self.tenant_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.client_request_id == client_request_id,
                IdempotencyKey.state == IdempotencyState.IN_FLIGHT,
            )
            .returning(IdempotencyKey.client_request_id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _require_key(self, scope: str, client_request_id: UUID) -> IdempotencyKey:
        statement = (
            select(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == self.tenant_id,
                IdempotencyKey.scope == scope,
                IdempotencyKey.client_request_id == client_request_id,
            )
            .execution_options(populate_existing=True)
        )
        key = (await self._session.execute(statement)).scalar_one_or_none()
        if key is None:
            raise NotFoundError("idempotency key", client_request_id)
        return key


class AgentRunRepository:
    """Run records bound to one trusted thread and one process owner.

    Writes are obtained through ``AgentRunOwner.runs`` so the advisory-lock
    check and the mutation use the same dedicated database connection.
    """

    def __init__(self, session: AsyncSession, scope: ThreadScope, owner_id: UUID) -> None:
        """Bind the repository to a trusted scope and the current owner."""
        self._session = session
        self.scope = scope
        self.owner_id = owner_id

    async def require_thread(self) -> Thread:
        """Resolve the canonical mapping; reject a foreign or closed thread."""
        scope = self.scope
        thread = await ThreadRepository(self._session, TenantScope(scope.tenant_id)).require(
            scope.thread_id
        )
        if thread.project_id != scope.project_id or thread.status is not ThreadStatus.ACTIVE:
            raise NotFoundError("thread", scope.thread_id)
        return thread

    async def get(self, run_id: UUID) -> AgentRun | None:
        """Read one run without widening tenant, project or thread access."""
        await self.require_thread()
        statement = select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.tenant_id == self.scope.tenant_id,
            AgentRun.project_id == self.scope.project_id,
            AgentRun.thread_id == self.scope.thread_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(
        self, *, client_request_id: UUID, based_on_context_version: int, run_id: UUID | None = None
    ) -> AgentRun:
        """Persist acceptance before execution; one active run is enforced by PostgreSQL."""
        await self.require_thread()
        run = AgentRun(
            id=run_id or uuid4(),
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            thread_id=self.scope.thread_id,
            owner_id=self.owner_id,
            client_request_id=client_request_id,
            status=AgentRunStatus.ACCEPTED,
            based_on_context_version=based_on_context_version,
            last_public_revision=0,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def set_status(
        self,
        run_id: UUID,
        status: AgentRunStatus,
        *,
        projection: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Advance this owner's active run; a terminal run can never be restarted implicitly.

        When ``projection`` is given, the final public ``PublicAgentState`` is
        stored alongside the transition, so a client that opens the chat after
        the run finished reads its real history instead of an empty one. It is
        only meaningful on a terminal transition and is ignored otherwise.
        """
        run = await self.get(run_id)
        if run is None or run.owner_id != self.owner_id:
            raise NotFoundError("run", run_id)
        if run.status not in ACTIVE_RUN_STATUSES:
            raise ValueError("terminal run requires an explicit new run")
        run.status = status
        run.finished_at = None if status in ACTIVE_RUN_STATUSES else datetime.now(UTC)
        run.last_public_revision += 1
        if projection is not None and status not in ACTIVE_RUN_STATUSES:
            run.public_projection = projection
        await self._session.flush()
        return run


ACTIVE_RUN_STATUSES = (
    AgentRunStatus.ACCEPTED,
    AgentRunStatus.RUNNING,
    AgentRunStatus.CANCELLING,
)
_OWNER_NAMESPACE = 1129337423
_OWNER_LOCK = 1


class AgentRunOwner:
    """Single-process ownership of one database, fenced by its own connection."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Use the dedicated connection whose session already holds the lock."""
        self._connection = connection
        self._serial = asyncio.Lock()
        self.id = uuid4()

    @asynccontextmanager
    async def transaction_connection(self) -> AsyncIterator[AsyncConnection]:
        """Lease the physical owner connection for one serialized atomic operation.

        Native framework adapters must use this connection, never an independent
        pool. A lost connection is terminal: the owner cannot reconnect.
        """
        async with self._serial:
            if self._connection.closed or self._connection.invalidated:
                raise RuntimeError("agent run ownership connection was lost")
            async with self._connection.begin():
                held = await self._connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                        "AND pid = pg_backend_pid() AND classid = :namespace AND objid = :key "
                        "AND objsubid = 2 AND granted)"
                    ),
                    {"namespace": _OWNER_NAMESPACE, "key": _OWNER_LOCK},
                )
                if not held:
                    raise RuntimeError("agent run ownership lock was lost")
                yield self._connection

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        async with (
            self.transaction_connection() as connection,
            AsyncSession(bind=connection, expire_on_commit=False) as session,
        ):
            yield session
            await session.flush()

    @asynccontextmanager
    async def runs(self, scope: ThreadScope) -> AsyncIterator[AgentRunRepository]:
        """Serialize scoped work on the connection that holds process ownership."""
        async with self._transaction() as session:
            yield AgentRunRepository(session, scope, self.id)

    async def resolve_thread_scope(
        self, *, project_id: UUID, thread_id: UUID
    ) -> ThreadScope | None:
        """Turn a project and thread id into a trusted scope, or ``None``.

        The tenant is read from the project row, never taken from the caller: a
        project belongs to exactly one tenant. The thread must belong to that
        exact project and the project must still be live. This crosses tenant
        scopes on purpose — it is how the internal RPC, which has no session,
        obtains the scope every owner operation requires.
        """
        async with self._transaction() as session:
            project = await session.get(Project, project_id)
            if project is None or project.deleted_at is not None:
                return None
            thread = await session.get(Thread, thread_id)
            if thread is None or thread.project_id != project_id:
                return None
            return ThreadScope(
                tenant_id=project.tenant_id,
                project_id=project_id,
                thread_id=thread_id,
            )

    async def find_run(self, run_id: UUID) -> AgentRun | None:
        """Read one run row by id alone, across scopes.

        Used by the RPC lifecycle endpoints to answer for a run this process
        did not start — after a restart, or for another dead worker's run that
        recovery has already marked ``interrupted``.
        """
        async with self._transaction() as session:
            return await session.get(AgentRun, run_id)

    async def latest_projection(self, scope: ThreadScope) -> dict[str, Any] | None:
        """The stored public projection of the newest run of this thread.

        A fresh run seeds its ``initial_state`` with this so a thread's history
        accumulates across runs instead of every reload showing only the last
        turn. ``None`` when the thread has no finished run with a projection.
        """
        async with self._transaction() as session:
            row = await session.scalar(
                select(AgentRun)
                .where(
                    AgentRun.tenant_id == scope.tenant_id,
                    AgentRun.project_id == scope.project_id,
                    AgentRun.thread_id == scope.thread_id,
                    AgentRun.public_projection.is_not(None),
                )
                .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
                .limit(1)
            )
        return None if row is None or row.public_projection is None else dict(row.public_projection)

    async def interrupt_active(self, *, only_current: bool = False) -> int:
        """Recover abandoned active runs, or finish this owner's bounded shutdown.

        This deliberately crosses tenant scopes only for process recovery. It is
        unavailable without the exclusive database owner lock. No checkpoint SQL
        or terminal run is modified.
        """
        async with self._transaction() as session:
            statement = update(AgentRun).where(AgentRun.status.in_(ACTIVE_RUN_STATUSES))
            if only_current:
                statement = statement.where(AgentRun.owner_id == self.id)
            else:
                statement = statement.where(AgentRun.owner_id != self.id)
            ids = await session.scalars(
                statement.values(
                    status=AgentRunStatus.INTERRUPTED,
                    finished_at=func.clock_timestamp(),
                    last_public_revision=AgentRun.last_public_revision + 1,
                ).returning(AgentRun.id)
            )
            return len(ids.all())


@asynccontextmanager
async def agent_run_owner(engine: AsyncEngine) -> AsyncIterator[AgentRunOwner]:
    """Acquire one worker per database; a second worker fails before recovery.

    The lock-holding connection also executes run writes, preventing a dead
    owner from mutating records through a reconnected or independent session.
    """
    async with engine.connect() as connection:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:namespace, :key)"),
            {"namespace": _OWNER_NAMESPACE, "key": _OWNER_LOCK},
        )
        await connection.commit()
        if not acquired:
            raise RuntimeError("another agent worker already owns this database")
        try:
            yield AgentRunOwner(connection)
        finally:
            if not connection.closed and not connection.invalidated:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :key)"),
                    {"namespace": _OWNER_NAMESPACE, "key": _OWNER_LOCK},
                )
                await connection.commit()
