"""Who owns a project, and which threads belong to it.

Ownership is the one check that is never demonstrative. A caller may not name
their tenant, and a project id in a URL proves nothing: the server looks the
project up and compares it with the authenticated session.

The workspace schema does not exist yet, so the lookup is a port. The in-memory
implementation is a stand-in for the repository that will replace it; the rule
it enforces — a project belongs to exactly one tenant and one owner, and a
thread belongs to exactly one project — does not change with the storage.
"""

from dataclasses import dataclass
from typing import Protocol

from counterparty_contracts import ProjectId, TenantId, ThreadId, UserId

__all__ = ["InMemoryProjectDirectory", "ProjectDirectory", "ProjectRecord"]


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


class InMemoryProjectDirectory:
    """Process-local ownership directory used until workspace storage lands."""

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
