"""Persistence interfaces and implementations for Counterparty Workspace."""

from . import reports as reports
from . import repositories as repositories
from . import roles as roles
from . import workspace as workspace
from .access import ProjectScope, TenantScope, ThreadScope
from .base import MONEY, NAMING_CONVENTION, Base, metadata
from .errors import (
    ContextVersionConflictError,
    IdempotencyConflictError,
    NotFoundError,
    ProjectCompanyLimitError,
    ProjectDeletedError,
    StorageError,
)
from .roles import DatabaseRole, Privilege
from .schemas import (
    MANAGED_SCHEMAS,
    REPORTS_SCHEMA,
    VERSION_TABLE_SCHEMA,
    WORKSPACE_SCHEMA,
)
from .session import create_database_engine, create_session_factory, unit_of_work
from .unit_of_work import AsyncUnitOfWork

__version__ = "0.1.0"

#: Metadata every mapped table is registered on. Importing this package is
#: enough for Alembic to see the full target schema; it opens no connection.
target_metadata = metadata

__all__ = [
    "MANAGED_SCHEMAS",
    "MONEY",
    "NAMING_CONVENTION",
    "REPORTS_SCHEMA",
    "VERSION_TABLE_SCHEMA",
    "WORKSPACE_SCHEMA",
    "AsyncUnitOfWork",
    "Base",
    "ContextVersionConflictError",
    "DatabaseRole",
    "IdempotencyConflictError",
    "NotFoundError",
    "Privilege",
    "ProjectCompanyLimitError",
    "ProjectDeletedError",
    "ProjectScope",
    "StorageError",
    "TenantScope",
    "ThreadScope",
    "create_database_engine",
    "create_session_factory",
    "metadata",
    "reports",
    "repositories",
    "roles",
    "target_metadata",
    "unit_of_work",
    "workspace",
]
