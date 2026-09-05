"""Which database objects these migrations are allowed to manage.

PostgreSQL also hosts schemas this project does not own. A framework-owned
namespace — for example an ``agent_state`` schema holding LangGraph checkpoint
tables, whose DDL belongs to the library and is applied as its own deployment
step — must stay invisible to autogenerate, so that a project revision can
never propose dropping it.

This lives outside ``env.py`` because ``env.py`` runs migrations on import and
therefore cannot be imported by a test.
"""

from alembic.runtime.environment import NameFilterParentNames, NameFilterType
from counterparty_storage import MANAGED_SCHEMAS

__all__ = ["MANAGED_SCHEMAS", "include_name"]


def include_name(
    name: str | None,
    type_: NameFilterType,
    parent_names: NameFilterParentNames,
) -> bool:
    """Restrict every schema comparison to the schemas this project owns."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    if type_ == "table":
        return parent_names.get("schema_name") in MANAGED_SCHEMAS
    return True
