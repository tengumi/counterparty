"""Mapped tables of the ``workspace`` schema.

Scope of this revision is the composition of a counterparty check: who owns it
(``tenants``, ``users``, ``memberships``), the check itself (``projects``), the
counterparties under review (``project_companies``), the chats inside it
(``threads``) and the request-id reservations that make a repeated write
harmless (``idempotency_keys``).

Rules encoded here rather than left to application discipline:

* Isolation is structural. ``tenant_id`` is carried by every row that belongs
  to a tenant, and a child row references its project by the composite key
  ``(id, tenant_id)``: no statement can move a thread or a counterparty into a
  different tenant, even by mistake, and a repository that forgets its
  ``WHERE tenant_id`` still cannot cross the boundary through a join.
* A project holds at most 20 counterparties. The limit is a numbered slot with
  a range check and a unique index over the active rows, so exceeding it is a
  database error rather than a count the application is trusted to perform.
* Idempotency is a primary key. The same ``(tenant_id, scope,
  client_request_id)`` cannot be inserted twice, so a retried request cannot
  create a second project even if two copies of it run at the same time.
* Removing a counterparty from a project sets ``removed_at``. The row, its
  pinned ``report_id`` and the source snapshot all survive, because the history
  of what was reviewed is not a consequence of the current composition.
* Framework-owned checkpoint tables are not mapped here. Their DDL belongs to
  the library that owns them and is applied as its own deployment step.
"""

import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..schemas import WORKSPACE_SCHEMA
from .enums import AgentRunStatus, CounterpartyRole, IdempotencyState, ThreadStatus, WorkflowStatus

MAX_PROJECT_COMPANIES: Final = 20
"""Counterparties one project may compare, matching the REST contract. A batch
that would exceed it is rejected as a whole, never silently truncated."""

_WORKFLOW_STATUS = Enum(
    WorkflowStatus,
    name="workflow_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)
_THREAD_STATUS = Enum(
    ThreadStatus,
    name="thread_status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)
_COUNTERPARTY_ROLE = Enum(
    CounterpartyRole,
    name="counterparty_role",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)
_IDEMPOTENCY_STATE = Enum(
    IdempotencyState,
    name="idempotency_state",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda enum: [member.value for member in enum],
)

_PROJECTS = f"{WORKSPACE_SCHEMA}.projects"


class WorkspaceBase(Base):
    """Abstract base pinning every mapped table to the ``workspace`` schema."""

    __abstract__ = True


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class Tenant(WorkspaceBase):
    """The owner boundary. Nothing is ever read across two tenants."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    slug: Mapped[str] = mapped_column(Text)
    """Stable human-readable handle, used by the demo fixture and by operations."""

    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class User(WorkspaceBase):
    """A person who can own projects and record decisions.

    The identity is global; a membership grants them access to one tenant. The
    row is never deleted while it is named as an author.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Membership(WorkspaceBase):
    """Access of one user to one tenant.

    This is the only place that answers "may this caller see this tenant". An
    ``actor_user_id`` taken from a request body is never such an answer.
    """

    __tablename__ = "memberships"
    __table_args__ = ({"schema": WORKSPACE_SCHEMA},)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{WORKSPACE_SCHEMA}.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{WORKSPACE_SCHEMA}.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Project(WorkspaceBase):
    """One counterparty check.

    ``context_version`` is the optimistic-concurrency token of the deal
    context: terms, composition and materials advance it, a rename does not.
    ``deleted_at`` closes access before the asynchronous cleanup finishes, so a
    deleted project stops accepting writes immediately.
    """

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_projects_id_tenant_id"),
        CheckConstraint("context_version >= 0", name="context_version_non_negative"),
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at",
            name="deleted_after_created",
        ),
        Index("ix_projects_tenant_id_updated_at", "tenant_id", "updated_at"),
        Index("ix_projects_owner_id", "owner_id"),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{WORKSPACE_SCHEMA}.tenants.id", ondelete="RESTRICT")
    )
    """``RESTRICT``: a tenant that still owns work is never removed implicitly."""

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{WORKSPACE_SCHEMA}.users.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(Text)
    default_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            f"{WORKSPACE_SCHEMA}.threads.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_projects_default_thread_id",
        )
    )
    """The chat opened first. ``NULL`` between creating the project and its
    first thread, and again if that thread is deleted: the project stays."""

    context_version: Mapped[int] = mapped_column(Integer, server_default="0")
    workflow_status: Mapped[WorkflowStatus] = mapped_column(
        _WORKFLOW_STATUS, server_default=WorkflowStatus.IN_PROGRESS.value
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.clock_timestamp()
    )
    """``clock_timestamp()`` rather than ``now()``: two changes made inside one
    transaction must still order, or the activity-sorted project list would
    depend on the row id instead of on what was touched last."""

    deleted_at: Mapped[datetime | None] = mapped_column()


class Thread(WorkspaceBase):
    """One persistent chat inside a project.

    ``id`` is the canonical ``thread_id`` used by the agent and by the UI; a
    session cookie never substitutes for it. Each thread owns its own
    checkpoint namespace, which is stored by the framework, not here.
    """

    __tablename__ = "threads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            [f"{_PROJECTS}.id", f"{_PROJECTS}.tenant_id"],
            name="fk_threads_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "project_id", name="uq_threads_id_project_id"),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="archived_state_matches_timestamp",
        ),
        Index("ix_threads_project_id_last_activity_at", "project_id", "last_activity_at"),
        Index("ix_threads_tenant_id", "tenant_id"),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column()
    """Carried on the row so the composite foreign key can pin the thread to
    the tenant of its project; it is not a second source of truth."""

    title: Mapped[str] = mapped_column(Text)
    status: Mapped[ThreadStatus] = mapped_column(
        _THREAD_STATUS, server_default=ThreadStatus.ACTIVE.value
    )
    last_activity_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column()


class ProjectCompany(WorkspaceBase):
    """One counterparty under review inside a project.

    The row pins the exact ``report_id`` the project reasons about, so a later
    snapshot never silently changes what was compared. Removing the
    counterparty sets ``removed_at`` and keeps both the row and the snapshot.
    """

    __tablename__ = "project_companies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            [f"{_PROJECTS}.id", f"{_PROJECTS}.tenant_id"],
            name="fk_project_companies_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"slot BETWEEN 1 AND {MAX_PROJECT_COMPANIES}",
            name="slot_within_company_limit",
        ),
        Index("ix_project_companies_company_id", "company_id"),
        Index("ix_project_companies_report_id", "report_id"),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column()
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.companies.id", ondelete="RESTRICT")
    )
    """``RESTRICT``: the shared report corpus is not deleted by workspace work,
    and a project never ends up pointing at a company that no longer exists."""

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.report_snapshots.id", ondelete="RESTRICT")
    )
    """The snapshot this project reasons about, pinned when the company was
    added. It outlives the counterparty's removal from the composition."""

    slot: Mapped[int] = mapped_column(Integer)
    """Numbered position 1..20. Together with the unique index over active rows
    this makes the company limit a database rule, not a counted query."""

    role: Mapped[CounterpartyRole] = mapped_column(
        _COUNTERPARTY_ROLE, server_default=CounterpartyRole.UNKNOWN.value
    )
    shortlisted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column()


#: The same counterparty may not appear twice in the active composition, and
#: the twenty numbered slots cannot be occupied more than once. Both indexes
#: cover only active rows, so a removed counterparty can be added again and its
#: history stays. They are declared here rather than in ``__table_args__``
#: because the partial condition is a real column expression.
Index(
    "uq_project_companies_active_company",
    ProjectCompany.project_id,
    ProjectCompany.company_id,
    unique=True,
    postgresql_where=ProjectCompany.removed_at.is_(None),
)
Index(
    "uq_project_companies_active_slot",
    ProjectCompany.project_id,
    ProjectCompany.slot,
    unique=True,
    postgresql_where=ProjectCompany.removed_at.is_(None),
)


class IdempotencyKey(WorkspaceBase):
    """One reserved request id and the resource it produced.

    The primary key is the whole idempotency mechanism: a repeated write cannot
    insert a second row, so it cannot create a second resource. A repeat with
    the *same* payload replays the stored identity; a repeat that arrives while
    the first one is still running is told so instead of racing it; a reuse of
    the same id for a *different* payload is refused, because returning the
    first resource would silently discard the second request.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "(state = 'in_flight' AND resource_id IS NULL AND completed_at IS NULL)"
            " OR (state = 'completed' AND resource_id IS NOT NULL"
            " AND completed_at IS NOT NULL)",
            name="completed_names_its_resource",
        ),
        Index("ix_idempotency_keys_created_at", "created_at"),
        {"schema": WORKSPACE_SCHEMA},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{WORKSPACE_SCHEMA}.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    """Operation the id was issued for, for example ``projects.create``. The
    same client id used for two different operations is two reservations."""

    client_request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    """Digest of the canonical request payload; how a reused id is detected."""

    state: Mapped[IdempotencyState] = mapped_column(_IDEMPOTENCY_STATE)
    resource_kind: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    response_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Optional replay body, when repeating the exact response matters."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column()


class AgentRun(WorkspaceBase):
    """Durable run lifecycle, separate from framework graph checkpoints."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            [f"{_PROJECTS}.id", f"{_PROJECTS}.tenant_id"],
            name="fk_agent_runs_project_id_tenant_id",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "project_id"],
            [f"{WORKSPACE_SCHEMA}.threads.id", f"{WORKSPACE_SCHEMA}.threads.project_id"],
            name="fk_agent_runs_thread_id_project_id",
            ondelete="CASCADE",
        ),
        CheckConstraint("based_on_context_version >= 0", name="context_version_non_negative"),
        CheckConstraint("last_public_revision >= 0", name="public_revision_non_negative"),
        CheckConstraint(
            "(status IN ('accepted', 'running', 'cancelling')) = (finished_at IS NULL)",
            name="terminal_status_matches_timestamp",
        ),
        UniqueConstraint(
            "tenant_id", "thread_id", "client_request_id", name="uq_agent_runs_request"
        ),
        {"schema": WORKSPACE_SCHEMA},
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column()
    project_id: Mapped[uuid.UUID] = mapped_column()
    thread_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column()
    client_request_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(
            AgentRunStatus,
            name="agent_run_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
        )
    )
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()
    based_on_context_version: Mapped[int] = mapped_column(Integer, server_default="0")
    last_public_revision: Mapped[int] = mapped_column(Integer, server_default="0")


Index(
    "uq_agent_runs_active_thread",
    AgentRun.thread_id,
    unique=True,
    postgresql_where=AgentRun.status.in_(
        [
            AgentRunStatus.ACCEPTED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.CANCELLING,
        ]
    ),
)
