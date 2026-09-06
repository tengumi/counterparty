"""Database schema names owned by this project.

PostgreSQL hosts more than the schemas declared here: framework-owned tables
(for example LangGraph checkpoint storage) live in their own namespace and are
created by their own deployment step. ``MANAGED_SCHEMAS`` is the allow-list our
migrations and autogenerate are permitted to touch, so an unmanaged schema is
never dropped or "corrected" by a project revision.
"""

from typing import Final

REPORTS_SCHEMA: Final = "reports"
WORKSPACE_SCHEMA: Final = "workspace"

#: Schemas created and versioned by this project's Alembic revisions.
MANAGED_SCHEMAS: Final[frozenset[str]] = frozenset({REPORTS_SCHEMA, WORKSPACE_SCHEMA})

#: Schema holding the Alembic version table; kept out of the managed schemas so
#: that a downgrade can drop them without destroying migration bookkeeping.
VERSION_TABLE_SCHEMA: Final = "public"
