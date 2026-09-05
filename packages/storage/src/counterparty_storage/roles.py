"""Database privileges of the four services, as data rather than as prose.

Each service connects as its own PostgreSQL role, and what that role may do is
decided by the database, not by the code it happens to run:

* ``importer`` fills the report corpus. It writes only inside ``reports`` and
  never sees a tenant's work.
* ``mcp`` answers questions about the report corpus. It reads ``reports`` and
  can write nowhere at all, so a prompt cannot turn a lookup into a change.
* ``ui_api`` serves the product. It reads both schemas and writes only inside
  ``workspace``: it cannot edit the provided report it is showing.
* ``agent`` reasons inside a project. It reads the project context it works on
  and, in this vertical, may update exactly one column — the activity time of a
  thread. It reaches the report corpus through MCP, so it holds no privilege on
  ``reports`` whatsoever, and it cannot rename, create or delete anything.

Two rules keep the matrix honest as the schema grows:

* a role that is granted a whole schema also receives default privileges there,
  so a table added by a later revision is covered automatically;
* a role listed table by table receives nothing by default, so its surface can
  only grow by an explicit, reviewable line in this file.

The roles are created ``NOLOGIN``. They are group roles: a deployment creates
its own login user and grants it the group, so no password is ever handled by a
migration. Framework-owned checkpoint storage lives in a namespace this project
does not own; granting privileges there belongs to the deployment step that
creates it, and is deliberately absent here.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from .schemas import REPORTS_SCHEMA, WORKSPACE_SCHEMA

__all__ = [
    "ALL_TABLES",
    "ROLE_GRANTS",
    "DatabaseRole",
    "Privilege",
    "TableGrant",
    "create_role_statements",
    "drop_role_statements",
    "grant_statements",
    "granted_schemas",
    "privileges_for",
    "revoke_statements",
]


class DatabaseRole(StrEnum):
    """PostgreSQL group role one service connects as."""

    IMPORTER = "counterparty_importer"
    UI_API = "counterparty_ui_api"
    MCP = "counterparty_mcp"
    AGENT = "counterparty_agent"


class Privilege(StrEnum):
    """Table privilege this project grants. ``TRUNCATE`` is never granted."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


ALL_TABLES: Final = None
"""Marker for "every table of the schema, including future ones"."""

_READ: Final = frozenset({Privilege.SELECT})
_APPEND: Final = frozenset({Privilege.SELECT, Privilege.INSERT, Privilege.UPDATE})
_FULL: Final = frozenset({Privilege.SELECT, Privilege.INSERT, Privilege.UPDATE, Privilege.DELETE})


@dataclass(frozen=True)
class TableGrant:
    """Privileges of one role on one table, or on a whole schema."""

    schema: str
    table: str | None
    """``ALL_TABLES`` grants the schema and its future tables at once."""

    privileges: frozenset[Privilege]
    columns: Mapping[Privilege, tuple[str, ...]] = field(default_factory=dict)
    """Privileges narrowed to named columns. A privilege listed here is granted
    on those columns only, which is how a role gets a write it needs without
    the rest of the row."""

    def __post_init__(self) -> None:
        """Reject a grant that could not be rendered as valid SQL.

        Raises:
            ValueError: If a column list belongs to a privilege the grant does
                not carry, or if a whole-schema grant tries to name columns.
        """
        unknown = set(self.columns) - self.privileges
        if unknown:
            raise ValueError(f"column list for a privilege that is not granted: {unknown}")
        if self.table is ALL_TABLES and self.columns:
            raise ValueError("a whole-schema grant cannot be narrowed to columns")

    @property
    def target(self) -> str:
        """SQL fragment naming what this grant applies to."""
        if self.table is ALL_TABLES:
            return f"ALL TABLES IN SCHEMA {self.schema}"
        return f"{self.schema}.{self.table}"


ROLE_GRANTS: Final[Mapping[DatabaseRole, tuple[TableGrant, ...]]] = {
    DatabaseRole.IMPORTER: (
        # Fills and corrects the report corpus. No DELETE: an imported snapshot
        # is superseded by a new one, never quietly removed.
        TableGrant(REPORTS_SCHEMA, ALL_TABLES, _APPEND),
    ),
    DatabaseRole.MCP: (
        # Read-only by construction, in both schemas' sense: it is not granted
        # workspace at all, so no tenant's work is reachable from a tool call.
        TableGrant(REPORTS_SCHEMA, ALL_TABLES, _READ),
    ),
    DatabaseRole.UI_API: (
        TableGrant(REPORTS_SCHEMA, ALL_TABLES, _READ),
        TableGrant(WORKSPACE_SCHEMA, ALL_TABLES, _FULL),
    ),
    DatabaseRole.AGENT: (
        # Enumerated table by table on purpose: a workspace table added later
        # stays invisible to the agent until someone adds a line here.
        TableGrant(WORKSPACE_SCHEMA, "projects", _READ),
        TableGrant(WORKSPACE_SCHEMA, "project_companies", _READ),
        TableGrant(
            WORKSPACE_SCHEMA,
            "threads",
            frozenset({Privilege.SELECT, Privilege.UPDATE}),
            columns={Privilege.UPDATE: ("last_activity_at",)},
        ),
    ),
}
"""The whole privilege matrix. Nothing outside this mapping is granted."""


def granted_schemas(role: DatabaseRole) -> frozenset[str]:
    """Return the schemas ``role`` may enter at all."""
    return frozenset(grant.schema for grant in ROLE_GRANTS[role])


def privileges_for(role: DatabaseRole, schema: str, table: str) -> frozenset[Privilege]:
    """Return the whole-row privileges ``role`` holds on one table.

    A privilege that is narrowed to columns is not a whole-row privilege and is
    therefore not reported here.
    """
    held: set[Privilege] = set()
    for grant in ROLE_GRANTS[role]:
        if grant.schema != schema or grant.table not in (ALL_TABLES, table):
            continue
        held |= {privilege for privilege in grant.privileges if privilege not in grant.columns}
    return frozenset(held)


def _ordered(privileges: Iterable[Privilege]) -> str:
    return ", ".join(sorted(privilege.value for privilege in privileges))


def create_role_statements() -> tuple[str, ...]:
    """Create the four group roles if the cluster does not have them yet.

    Roles are cluster-wide, so creation is written to be safe on a cluster that
    already hosts another database of this project.
    """
    return tuple(
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role.value}') THEN "
        f"CREATE ROLE {role.value} NOLOGIN; "
        "END IF; END $$;"
        for role in DatabaseRole
    )


def _grants_for(role: DatabaseRole) -> list[str]:
    statements: list[str] = []
    for schema in sorted(granted_schemas(role)):
        statements.append(f"GRANT USAGE ON SCHEMA {schema} TO {role.value};")
    for grant in ROLE_GRANTS[role]:
        plain = {privilege for privilege in grant.privileges if privilege not in grant.columns}
        if plain:
            statements.append(f"GRANT {_ordered(plain)} ON {grant.target} TO {role.value};")
        for privilege, columns in sorted(grant.columns.items()):
            names = ", ".join(columns)
            statements.append(
                f"GRANT {privilege.value} ({names}) ON {grant.target} TO {role.value};"
            )
        if grant.table is ALL_TABLES:
            statements.append(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {grant.schema} "
                f"GRANT {_ordered(grant.privileges)} ON TABLES TO {role.value};"
            )
    return statements


def grant_statements(roles: Sequence[DatabaseRole] | None = None) -> tuple[str, ...]:
    """Return the GRANT statements that realise the matrix."""
    return tuple(
        statement for role in (roles or tuple(DatabaseRole)) for statement in _grants_for(role)
    )


def _revokes_for(role: DatabaseRole) -> list[str]:
    statements: list[str] = []
    for grant in ROLE_GRANTS[role]:
        if grant.table is ALL_TABLES:
            statements.append(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {grant.schema} "
                f"REVOKE {_ordered(grant.privileges)} ON TABLES FROM {role.value};"
            )
        statements.append(f"REVOKE ALL ON {grant.target} FROM {role.value};")
    for schema in sorted(granted_schemas(role)):
        statements.append(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {role.value};")
        statements.append(f"REVOKE ALL ON SCHEMA {schema} FROM {role.value};")
    return statements


def revoke_statements(roles: Sequence[DatabaseRole] | None = None) -> tuple[str, ...]:
    """Return the REVOKE statements that undo :func:`grant_statements`."""
    return tuple(
        statement for role in (roles or tuple(DatabaseRole)) for statement in _revokes_for(role)
    )


def drop_role_statements() -> tuple[str, ...]:
    """Drop the group roles, after their privileges have been revoked.

    ``DROP ROLE`` fails loudly if a privilege was missed, which is the point:
    a downgrade must not leave a half-privileged role behind.
    """
    return tuple(f"DROP ROLE IF EXISTS {role.value};" for role in reversed(tuple(DatabaseRole)))
