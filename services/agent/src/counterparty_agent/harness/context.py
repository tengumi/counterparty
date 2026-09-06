"""Project and thread context assembly (AG-02, Specs 04 §3, 01 §10).

Two properties matter more than the wording of the prompt.

*Isolation.* A context is built for exactly one ``ThreadScope``. Sibling
threads of the same project are never read: their history stays in their own
LangGraph checkpoint, and this module offers no way to widen a scope. What the
threads of one project do share is the project layer -- goal, counterparties
and ``context_version`` -- which is reloaded on every command.

*Authority.* Every layer names where its values came from. Policy and domain
notes are server-side configuration; project values carry the project's own
version; report facts are not inlined here at all, because they are read
through MCP tools so that their evidence references stay resolvable.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from counterparty_storage import TenantScope, ThreadScope, unit_of_work
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .filesystem import thread_workspace_root
from .prompts import DOMAIN_NOTES, render_system_prompt


@dataclass(frozen=True, slots=True)
class CompanyContext:
    """One counterparty pinned in the project, with its report snapshot."""

    company_id: UUID
    report_id: UUID
    slot: int
    role: str
    shortlisted: bool = False
    inn: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """The project layer, shared by every thread of the project."""

    project_id: UUID
    tenant_id: UUID
    title: str
    workflow_status: str
    context_version: int
    companies: tuple[CompanyContext, ...] = ()


@dataclass(frozen=True, slots=True)
class ThreadContext:
    """The dialogue layer of exactly one working session."""

    thread_id: UUID
    title: str
    status: str


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Everything the harness is allowed to put in front of the model."""

    project: ProjectContext
    thread: ThreadContext
    workspace_root: str
    domain_notes: str = field(default=DOMAIN_NOTES)
    relevant_notes: str = ""
    """Domain-reference fragments selected for the current question
    (:func:`counterparty_agent.harness.knowledge.lookup`); empty until the
    runner fills it, and empty when nothing matched."""

    def render(self) -> str:
        """Render the layered system prompt for this thread."""
        return render_system_prompt(self)


class ContextSource(Protocol):
    """Where the project and thread layers are read from."""

    async def load(self, scope: ThreadScope) -> AgentContext:
        """Load the context of exactly one authorized thread."""
        ...


class WorkspaceContextSource:
    """Read the project and thread layers from the ``workspace`` schema."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Bind the source to an application-scoped session factory."""
        self._session_factory = session_factory

    async def load(self, scope: ThreadScope) -> AgentContext:
        """Load one thread and its project; sibling threads are never read."""
        tenant_scope = TenantScope(tenant_id=scope.tenant_id, actor_user_id=scope.actor_user_id)
        async with unit_of_work(self._session_factory, tenant_scope) as uow:
            thread = await uow.threads.require(scope.thread_id)
            if thread.project_id != scope.project_id:
                raise PermissionError("thread does not belong to the authorized project")
            project = await uow.projects.require(scope.project_id)
            companies = await uow.project_companies.list_active(
                tenant_scope.project(scope.project_id)
            )
            return build_context(
                project_id=project.id,
                tenant_id=project.tenant_id,
                title=project.title,
                workflow_status=project.workflow_status.value,
                context_version=project.context_version,
                companies=[
                    CompanyContext(
                        company_id=company.company_id,
                        report_id=company.report_id,
                        slot=company.slot,
                        role=company.role.value,
                        shortlisted=company.shortlisted,
                    )
                    for company in companies
                ],
                thread_id=thread.id,
                thread_title=thread.title,
                thread_status=thread.status.value,
            )


def build_context(
    *,
    project_id: UUID,
    tenant_id: UUID,
    title: str,
    workflow_status: str,
    context_version: int,
    companies: Sequence[CompanyContext],
    thread_id: UUID,
    thread_title: str,
    thread_status: str,
) -> AgentContext:
    """Assemble the two layers for one thread of one project."""
    return AgentContext(
        project=ProjectContext(
            project_id=project_id,
            tenant_id=tenant_id,
            title=title,
            workflow_status=workflow_status,
            context_version=context_version,
            companies=tuple(sorted(companies, key=lambda company: company.slot)),
        ),
        thread=ThreadContext(thread_id=thread_id, title=thread_title, status=thread_status),
        workspace_root=thread_workspace_root(project_id, thread_id),
    )
