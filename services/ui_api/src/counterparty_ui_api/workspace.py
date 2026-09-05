"""Who owns a project, and which threads belong to it.

Ownership is the one check that is never demonstrative. A caller may not name
their tenant, and a project id in a URL proves nothing: the server looks the
project up and compares it with the authenticated session.

The lookup is a port with two implementations. :class:`StorageProjectDirectory`
reads the ``workspace`` schema through the tenant-scoped repositories, so the
tenant filter is applied by the repository rather than by this module;
:class:`InMemoryProjectDirectory` stays for tests that exercise the dependency
without a database. The rule both enforce — a project belongs to exactly one
tenant and one owner, and a thread belongs to exactly one project — does not
change with the storage.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from counterparty_contracts import ProjectId, TenantId, ThreadId, UserId
from counterparty_storage import AsyncUnitOfWork

__all__ = [
    "InMemoryProjectDirectory",
    "ProjectDirectory",
    "ProjectRecord",
    "StorageProjectDirectory",
]


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """The ownership facts of one project."""

    project_id: ProjectId
    tenant_id: TenantId
    owner_user_id: UserId


class ProjectDirectory(Protocol):
    """Read-only access to project and thread ownership."""

    async def find_project(self, project_id: ProjectId) -> ProjectRecord | None:
        """Return the project's ownership record, or ``None`` if there is none."""
        ...

    async def thread_belongs_to_project(
        self, *, project_id: ProjectId, thread_id: ThreadId
    ) -> bool:
        """Whether the thread is part of that project."""
        ...


class StorageProjectDirectory:
    """Ownership read from the ``workspace`` schema of one tenant.

    The unit of work is already bound to the caller's tenant, so a project of
    another tenant is not merely rejected here: it is not reachable by this
    repository at all.
    """

    def __init__(self, uow: AsyncUnitOfWork) -> None:
        """Bind the directory to the transaction of one request."""
        self._uow = uow

    async def find_project(self, project_id: ProjectId) -> ProjectRecord | None:
        """Return the ownership record of a project of this tenant.

        A deleted project is not returned: access closes when the deletion is
        accepted, not when its cleanup finishes.
        """
        project = await self._uow.projects.get(UUID(str(project_id)))
        if project is None:
            return None
        return ProjectRecord(
            project_id=project_id,
            tenant_id=TenantId(project.tenant_id),
            owner_user_id=UserId(project.owner_id),
        )

    async def thread_belongs_to_project(
        self, *, project_id: ProjectId, thread_id: ThreadId
    ) -> bool:
        """Whether the chat is part of that exact project of this tenant."""
        thread = await self._uow.threads.get(UUID(str(thread_id)))
        return thread is not None and thread.project_id == UUID(str(project_id))


class InMemoryProjectDirectory:
    """Process-local ownership directory used by tests without a database."""

    def __init__(self) -> None:
        """Start with no projects."""
        self._projects: dict[ProjectId, ProjectRecord] = {}
        self._threads: dict[ThreadId, ProjectId] = {}

    def add_project(
        self, *, project_id: ProjectId, tenant_id: TenantId, owner_user_id: UserId
    ) -> ProjectRecord:
        """Register one project and return its record."""
        record = ProjectRecord(
            project_id=project_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        self._projects[project_id] = record
        return record

    def add_thread(self, *, project_id: ProjectId, thread_id: ThreadId) -> None:
        """Attach one thread to a project it belongs to."""
        self._threads[thread_id] = project_id

    async def find_project(self, project_id: ProjectId) -> ProjectRecord | None:
        """Return the ownership record of a project."""
        return self._projects.get(project_id)

    async def thread_belongs_to_project(
        self, *, project_id: ProjectId, thread_id: ThreadId
    ) -> bool:
        """Whether the thread belongs to that exact project."""
        return self._threads.get(thread_id) == project_id
