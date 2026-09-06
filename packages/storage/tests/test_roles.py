"""The privilege matrix of the four service roles.

These checks are about the declaration; ``migrations/tests/test_role_privileges``
proves the same statements against a running PostgreSQL, including that a
forbidden operation actually fails.
"""

import pytest

from counterparty_storage import REPORTS_SCHEMA, WORKSPACE_SCHEMA
from counterparty_storage.roles import (
    ALL_TABLES,
    ROLE_GRANTS,
    DatabaseRole,
    Privilege,
    TableGrant,
    create_role_statements,
    drop_role_statements,
    grant_statements,
    granted_schemas,
    privileges_for,
    revoke_statements,
)

WRITE = {Privilege.INSERT, Privilege.UPDATE, Privilege.DELETE}


def test_importer_writes_reports_and_cannot_see_workspace() -> None:
    """The import job never reaches a tenant's work."""
    assert granted_schemas(DatabaseRole.IMPORTER) == {REPORTS_SCHEMA}
    held = privileges_for(DatabaseRole.IMPORTER, REPORTS_SCHEMA, "report_snapshots")
    assert {Privilege.SELECT, Privilege.INSERT, Privilege.UPDATE} <= held
    assert Privilege.DELETE not in held


def test_mcp_only_reads_reports() -> None:
    """A tool call cannot turn into a write, and cannot reach workspace."""
    assert granted_schemas(DatabaseRole.MCP) == {REPORTS_SCHEMA}
    held = privileges_for(DatabaseRole.MCP, REPORTS_SCHEMA, "companies")
    assert held == {Privilege.SELECT}
    assert not privileges_for(DatabaseRole.MCP, WORKSPACE_SCHEMA, "projects")


def test_ui_api_reads_both_schemas_and_writes_only_workspace() -> None:
    """The product API cannot edit the provided report it is showing."""
    assert granted_schemas(DatabaseRole.UI_API) == {REPORTS_SCHEMA, WORKSPACE_SCHEMA}
    assert privileges_for(DatabaseRole.UI_API, REPORTS_SCHEMA, "companies") == {Privilege.SELECT}
    workspace = privileges_for(DatabaseRole.UI_API, WORKSPACE_SCHEMA, "projects")
    assert workspace >= WRITE


def test_agent_holds_nothing_on_reports() -> None:
    """The agent reads report facts through MCP, not through the database."""
    assert granted_schemas(DatabaseRole.AGENT) == {WORKSPACE_SCHEMA}
    assert not privileges_for(DatabaseRole.AGENT, REPORTS_SCHEMA, "report_snapshots")


def test_agent_reads_context_and_writes_only_one_column() -> None:
    """The agent may record activity, not rename or delete a user's work."""
    assert privileges_for(DatabaseRole.AGENT, WORKSPACE_SCHEMA, "projects") == {Privilege.SELECT}
    threads = privileges_for(DatabaseRole.AGENT, WORKSPACE_SCHEMA, "threads")
    assert threads == {Privilege.SELECT}, "UPDATE is column scoped, not whole row"
    statements = grant_statements([DatabaseRole.AGENT])
    assert any(
        "GRANT UPDATE (last_activity_at) ON workspace.threads" in statement
        for statement in statements
    )
    assert not privileges_for(DatabaseRole.AGENT, WORKSPACE_SCHEMA, "idempotency_keys")


def test_only_whole_schema_grants_cover_future_tables() -> None:
    """A table added later widens a role only where that was intended.

    ``ui_api`` is granted the workspace schema, so a new workspace table is
    usable at once. The agent is listed table by table, so a new table stays
    invisible to it until someone adds a line to the matrix.
    """
    ui_api = grant_statements([DatabaseRole.UI_API])
    assert any(
        statement.startswith("ALTER DEFAULT PRIVILEGES IN SCHEMA workspace") for statement in ui_api
    )
    agent = grant_statements([DatabaseRole.AGENT])
    assert not any(statement.startswith("ALTER DEFAULT PRIVILEGES") for statement in agent)


def test_no_role_is_granted_a_schema_it_holds_no_table_in() -> None:
    """USAGE is derived from the table grants, never granted on its own."""
    for role in DatabaseRole:
        schemas = {grant.schema for grant in ROLE_GRANTS[role]}
        for statement in grant_statements([role]):
            if statement.startswith("GRANT USAGE ON SCHEMA"):
                assert statement.split()[4] in schemas


def test_truncate_is_never_granted() -> None:
    """No service may empty a table; deletion is a row-level decision."""
    assert {privilege.value for privilege in Privilege} == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    assert not any("TRUNCATE" in statement for statement in grant_statements())


def test_every_grant_has_a_matching_database_local_revoke() -> None:
    """A downgrade hands back grants without deleting cluster-wide roles."""
    for role in DatabaseRole:
        granted = grant_statements([role])
        revoked = revoke_statements([role])
        for grant in ROLE_GRANTS[role]:
            assert any(grant.target in statement for statement in granted)
            assert any(grant.target in statement for statement in revoked)
    decommission = drop_role_statements()
    assert len(decommission) == len(DatabaseRole)
    assert all(statement.startswith("DROP ROLE IF EXISTS") for statement in decommission)


def test_roles_are_created_without_login() -> None:
    """They are group roles; a migration never handles a password."""
    statements = create_role_statements()
    assert len(statements) == len(DatabaseRole)
    for statement in statements:
        assert "NOLOGIN" in statement
        assert "PASSWORD" not in statement


def test_a_grant_cannot_name_columns_of_a_privilege_it_lacks() -> None:
    """A malformed row of the matrix is refused when it is declared."""
    with pytest.raises(ValueError, match="not granted"):
        TableGrant(
            WORKSPACE_SCHEMA,
            "threads",
            frozenset({Privilege.SELECT}),
            columns={Privilege.UPDATE: ("title",)},
        )
    with pytest.raises(ValueError, match="cannot be narrowed"):
        TableGrant(
            WORKSPACE_SCHEMA,
            ALL_TABLES,
            frozenset({Privilege.UPDATE}),
            columns={Privilege.UPDATE: ("title",)},
        )
