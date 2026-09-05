"""Persistence interfaces and implementations for Counterparty Workspace."""

from . import reports as reports
from .base import MONEY, NAMING_CONVENTION, Base, metadata
from .schemas import (
    MANAGED_SCHEMAS,
    REPORTS_SCHEMA,
    VERSION_TABLE_SCHEMA,
    WORKSPACE_SCHEMA,
)

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
    "Base",
    "metadata",
    "reports",
    "target_metadata",
]
