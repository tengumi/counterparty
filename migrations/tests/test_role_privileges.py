"""What the four service roles may and may not do, asked of PostgreSQL itself.

``packages/storage`` asserts the matrix as data; these tests apply it through
revision ``0004`` and then try the forbidden operation as each role. A role is
only verified once the database has refused it.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from counterparty_storage.roles import DatabaseRole
from psycopg import errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

FORBIDDEN: dict[DatabaseRole, tuple[str, ...]] = {
    # Fills the report corpus; a tenant's work is not reachable from it, and an
    # imported snapshot is superseded rather than deleted.
    DatabaseRole.IMPORTER: (
        "SELECT count(*) FROM workspace.projects",
        "DELETE FROM reports.companies",
    ),
    # A lookup can never become a change, in either schema.
    DatabaseRole.MCP: (
        "INSERT INTO reports.companies (id, inn) VALUES (gen_random_uuid(), '0')",
        "UPDATE reports.companies SET inn = '0'",
        "SELECT count(*) FROM workspace.projects",
    ),
    # Serves the product, and cannot edit the provided report it is showing.
    DatabaseRole.UI_API: (
        "UPDATE reports.companies SET inn = '0'",
        "INSERT INTO reports.companies (id, inn) VALUES (gen_random_uuid(), '0')",
        "DELETE FROM reports.companies",
    ),
    # Reaches report facts through MCP, reads only the project context, and of
    # a thread may touch exactly one column.
    DatabaseRole.AGENT: (
        "SELECT count(*) FROM reports.companies",
        "SELECT count(*) FROM workspace.users",
        "UPDATE workspace.threads SET title = 'renamed'",
        "DELETE FROM workspace.threads",
        "INSERT INTO workspace.projects (id, tenant_id, title) "
        "VALUES (gen_random_uuid(), gen_random_uuid(), 'x')",
    ),
}

ALLOWED: dict[DatabaseRole, tuple[str, ...]] = {
    DatabaseRole.IMPORTER: ("SELECT count(*) FROM reports.companies",),
    DatabaseRole.MCP: ("SELECT count(*) FROM reports.report_snapshots",),
    DatabaseRole.UI_API: (
        "SELECT count(*) FROM reports.companies",
        "SELECT count(*) FROM workspace.projects",
        "DELETE FROM workspace.threads WHERE false",
    ),
    DatabaseRole.AGENT: (
        "SELECT count(*) FROM workspace.projects",
        "SELECT count(*) FROM workspace.project_companies",
        "UPDATE workspace.threads SET last_activity_at = now() WHERE false",
    ),
}


@pytest.fixture
def at_head(alembic_config: Config, engine: Engine) -> Iterator[Connection]:
    """A connection to a database that carries the applied privilege matrix."""
    command.upgrade(alembic_config, "head")
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        command.downgrade(alembic_config, "base")


def _as_role(connection: Connection, role: DatabaseRole, statement: str) -> None:
    """Run one statement as ``role`` and undo whatever it managed to do."""
    transaction = connection.begin()
    try:
        connection.execute(text(f"SET LOCAL ROLE {role.value}"))
        connection.execute(text(statement))
    finally:
        transaction.rollback()


@pytest.mark.parametrize("role", list(DatabaseRole))
def test_the_database_refuses_what_a_role_may_not_do(
    at_head: Connection, role: DatabaseRole
) -> None:
    """Every forbidden statement is stopped by PostgreSQL, not by our code."""
    for statement in FORBIDDEN[role]:
        with pytest.raises(DBAPIError) as raised:
            _as_role(at_head, role, statement)
        assert isinstance(raised.value.orig, errors.InsufficientPrivilege), statement


@pytest.mark.parametrize("role", list(DatabaseRole))
def test_a_role_can_still_do_its_own_work(at_head: Connection, role: DatabaseRole) -> None:
    """The matrix is restrictive without taking away what the service needs."""
    for statement in ALLOWED[role]:
        _as_role(at_head, role, statement)


def test_no_role_may_log_in_on_its_own(at_head: Connection) -> None:
    """The roles are groups; a deployment grants them to its own login user."""
    rows = at_head.execute(
        text("SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname = ANY(:names)"),
        {"names": [role.value for role in DatabaseRole]},
    ).all()
    assert {row.rolname for row in rows} == {role.value for role in DatabaseRole}
    assert all(not row.rolcanlogin and not row.rolsuper for row in rows)
