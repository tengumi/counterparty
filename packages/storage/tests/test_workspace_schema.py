"""Structural guarantees of the ``workspace`` schema."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table

from counterparty_storage import MANAGED_SCHEMAS, WORKSPACE_SCHEMA, metadata
from counterparty_storage.workspace import (
    MAX_PROJECT_COMPANIES,
    CounterpartyRole,
    IdempotencyState,
    ThreadStatus,
    WorkflowStatus,
)

WORKSPACE_VERTICAL = {
    "tenants",
    "users",
    "memberships",
    "projects",
    "threads",
    "project_companies",
    "idempotency_keys",
    "agent_runs",
}


def _table(name: str) -> Table:
    return metadata.tables[f"{WORKSPACE_SCHEMA}.{name}"]


def test_workspace_vertical_is_mapped() -> None:
    """The mapped workspace tables are exactly this vertical."""
    mapped = {table.name for table in metadata.sorted_tables if table.schema == WORKSPACE_SCHEMA}
    assert mapped == WORKSPACE_VERTICAL
    assert WORKSPACE_SCHEMA in MANAGED_SCHEMAS


def test_enum_values_match_the_public_contract() -> None:
    """A workspace row maps onto the REST DTO without renaming anything."""
    assert [status.value for status in WorkflowStatus] == [
        "in_progress",
        "needs_information",
        "decision_recorded",
    ]
    assert [status.value for status in ThreadStatus] == ["active", "archived"]
    assert [role.value for role in CounterpartyRole] == [
        "supplier",
        "buyer",
        "contractor",
        "other",
        "unknown",
    ]
    assert [state.value for state in IdempotencyState] == ["in_flight", "completed"]


def test_project_columns_match_the_rest_contract() -> None:
    """Every field the project DTO promises has a column of the same name."""
    projects = _table("projects")
    expected = {
        "id",
        "tenant_id",
        "owner_id",
        "title",
        "default_thread_id",
        "context_version",
        "workflow_status",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert set(projects.c.keys()) == expected
    assert projects.c.default_thread_id.nullable
    assert projects.c.deleted_at.nullable


def test_children_are_pinned_to_the_tenant_of_their_project() -> None:
    """A thread or a counterparty cannot be moved into another tenant.

    The child references ``projects (id, tenant_id)``, so the pair has to keep
    matching; a single ``project_id`` foreign key would not say that.
    """
    for name in ("threads", "project_companies"):
        table = _table(name)
        assert "tenant_id" in table.c
        composite = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
            and {column.name for column in constraint.columns} == {"project_id", "tenant_id"}
        ]
        assert len(composite) == 1, name
        assert composite[0].ondelete == "CASCADE"
        referred = {element.target_fullname for element in composite[0].elements}
        assert referred == {
            f"{WORKSPACE_SCHEMA}.projects.id",
            f"{WORKSPACE_SCHEMA}.projects.tenant_id",
        }


def test_the_report_corpus_is_never_deleted_by_workspace_work() -> None:
    """Removing a counterparty leaves the company and the snapshot alone."""
    project_companies = _table("project_companies")
    targets = {
        element.target_fullname: constraint.ondelete
        for constraint in project_companies.foreign_key_constraints
        for element in constraint.elements
    }
    assert targets["reports.companies.id"] == "RESTRICT"
    assert targets["reports.report_snapshots.id"] == "RESTRICT"
    assert project_companies.c.removed_at.nullable
    assert not project_companies.c.report_id.nullable


def test_the_company_limit_is_a_database_rule() -> None:
    """Twenty numbered slots, each usable by one active row at a time."""
    project_companies = _table("project_companies")
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in project_companies.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert (
        f"BETWEEN 1 AND {MAX_PROJECT_COMPANIES}"
        in checks["ck_project_companies_slot_within_company_limit"]
    )
    slot_index = _index(project_companies, "uq_project_companies_active_slot")
    assert slot_index.unique
    assert slot_index.dialect_options["postgresql"]["where"] is not None
    company_index = _index(project_companies, "uq_project_companies_active_company")
    assert company_index.unique


def _index(table: Table, name: str) -> Index:
    matching = [index for index in table.indexes if index.name == name]
    assert matching, f"{name} is not defined on {table.name}"
    return matching[0]


def test_idempotency_is_a_primary_key_not_an_application_check() -> None:
    """The same request id cannot be inserted twice, by anyone."""
    keys = _table("idempotency_keys")
    assert [column.name for column in keys.primary_key.columns] == [
        "tenant_id",
        "scope",
        "client_request_id",
    ]
    assert not keys.c.request_fingerprint.nullable
    assert keys.c.resource_id.nullable


def test_a_completed_reservation_names_what_it_created() -> None:
    """A reservation cannot be completed without the resource it produced."""
    keys = _table("idempotency_keys")
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in keys.constraints
        if isinstance(constraint, CheckConstraint)
    }
    condition = checks["ck_idempotency_keys_completed_names_its_resource"]
    assert "resource_id IS NOT NULL" in condition
    assert "completed_at IS NOT NULL" in condition


def test_archiving_a_thread_records_when_it_happened() -> None:
    """An archived chat always carries its archive time, and only then."""
    threads = _table("threads")
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in threads.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "archived_at" in checks["ck_threads_archived_state_matches_timestamp"]


def test_projects_are_indexed_for_the_activity_ordered_list() -> None:
    """The project list of a tenant is served by an index, per Specs 02 §6."""
    names = {index.name for index in _table("projects").indexes}
    assert "ix_projects_tenant_id_updated_at" in names
