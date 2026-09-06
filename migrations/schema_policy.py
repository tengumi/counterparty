"""Exclude framework-owned tables while managing reports and workspace.

AsyncPostgresSaver owns its own DDL inside workspace. Its exact table names are
excluded from Alembic comparison, so autogenerate never proposes dropping them.
"""

from alembic.runtime.environment import NameFilterParentNames, NameFilterType
from counterparty_storage import MANAGED_SCHEMAS

__all__ = ["MANAGED_SCHEMAS", "include_name"]

FRAMEWORK_TABLES = frozenset(
    {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    }
)


def include_name(
    name: str | None,
    type_: NameFilterType,
    parent_names: NameFilterParentNames,
) -> bool:
    """Restrict every schema comparison to the schemas this project owns."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    if type_ == "table":
        return parent_names.get("schema_name") in MANAGED_SCHEMAS and not (
            parent_names.get("schema_name") == "workspace" and name in FRAMEWORK_TABLES
        )
    return True
