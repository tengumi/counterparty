"""The scope a repository is allowed to see.

Isolation runs through ``tenant_id``, ``project_id`` and ``thread_id``. A
repository is constructed *with* its scope instead of accepting one per call,
so a query cannot be written that forgets it: there is no method that takes a
project id without a tenant already fixed.

A scope narrows in one direction only. ``TenantScope.project()`` produces a
project scope for that tenant, and nothing produces a scope for another tenant,
so a caller cannot widen its own access by constructing a value.
"""

from dataclasses import dataclass
from uuid import UUID

__all__ = ["ProjectScope", "TenantScope", "ThreadScope"]


@dataclass(frozen=True, slots=True)
class TenantScope:
    """Everything one authenticated caller of one tenant may reach."""

    tenant_id: UUID
    actor_user_id: UUID | None = None
    """The authenticated caller. Never taken from a request body; ``None`` for
    a background job that acts for the tenant rather than for a person."""

    def project(self, project_id: UUID) -> "ProjectScope":
        """Narrow this scope to one project of the same tenant."""
        return ProjectScope(
            tenant_id=self.tenant_id,
            actor_user_id=self.actor_user_id,
            project_id=project_id,
        )


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """One project of one tenant."""

    tenant_id: UUID
    project_id: UUID
    actor_user_id: UUID | None = None

    def thread(self, thread_id: UUID) -> "ThreadScope":
        """Narrow this scope to one chat of the same project."""
        return ThreadScope(
            tenant_id=self.tenant_id,
            actor_user_id=self.actor_user_id,
            project_id=self.project_id,
            thread_id=thread_id,
        )

    def widen(self) -> TenantScope:
        """Return the tenant scope this project scope was narrowed from."""
        return TenantScope(tenant_id=self.tenant_id, actor_user_id=self.actor_user_id)


@dataclass(frozen=True, slots=True)
class ThreadScope:
    """One chat of one project of one tenant."""

    tenant_id: UUID
    project_id: UUID
    thread_id: UUID
    actor_user_id: UUID | None = None
