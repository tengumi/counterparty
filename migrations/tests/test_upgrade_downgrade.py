"""End-to-end migration checks against a real PostgreSQL."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from counterparty_storage import REPORTS_SCHEMA, WORKSPACE_SCHEMA, metadata
from sqlalchemy import Engine, create_engine, inspect, text


def _expected(schema: str) -> set[str]:
    """Tables the mapped models place in one schema."""
    return {table.name for table in metadata.sorted_tables if table.schema == schema}


EXPECTED_REPORTS = _expected(REPORTS_SCHEMA)
EXPECTED_WORKSPACE = _expected(WORKSPACE_SCHEMA)


def _schemas(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT schema_name FROM information_schema.schemata"))
        return {row[0] for row in rows}


@contextmanager
def _database_url(url: str) -> Iterator[None]:
    """Point one Alembic command at a selected database."""
    previous = os.environ.get("COUNTERPARTY_DATABASE_URL")
    os.environ["COUNTERPARTY_DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("COUNTERPARTY_DATABASE_URL", None)
        else:
            os.environ["COUNTERPARTY_DATABASE_URL"] = previous


def test_upgrade_creates_both_schemas_and_their_tables(
    alembic_config: Config, engine: Engine
) -> None:
    """Upgrading to head builds exactly the mapped tables of both schemas."""
    command.upgrade(alembic_config, "head")
    try:
        assert {REPORTS_SCHEMA, WORKSPACE_SCHEMA} <= _schemas(engine)
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema=REPORTS_SCHEMA)) == EXPECTED_REPORTS
        assert set(inspector.get_table_names(schema=WORKSPACE_SCHEMA)) == EXPECTED_WORKSPACE
    finally:
        command.downgrade(alembic_config, "base")


def test_downgrade_removes_everything_it_created(alembic_config: Config, engine: Engine) -> None:
    """Downgrading to base leaves no schema or table behind, so the migration is reversible."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    remaining = _schemas(engine)
    assert REPORTS_SCHEMA not in remaining
    assert WORKSPACE_SCHEMA not in remaining
    with engine.connect() as connection:
        version = connection.execute(text("SELECT count(*) FROM public.alembic_version")).scalar()
    assert version == 0


def test_upgrade_is_repeatable_after_a_downgrade(alembic_config: Config, engine: Engine) -> None:
    """A rolled back deployment can be applied again without manual cleanup."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema=REPORTS_SCHEMA)) == EXPECTED_REPORTS
        assert set(inspector.get_table_names(schema=WORKSPACE_SCHEMA)) == EXPECTED_WORKSPACE
    finally:
        command.downgrade(alembic_config, "base")


def test_no_model_drift_between_metadata_and_head(alembic_config: Config, engine: Engine) -> None:
    """Schema at head matches the mapped models, so autogenerate has nothing to propose."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from schema_policy import include_name

    command.upgrade(alembic_config, "head")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "target_metadata": metadata,
                    "include_schemas": True,
                    "include_name": include_name,
                    "version_table_schema": "public",
                    "compare_type": True,
                },
            )
            assert compare_metadata(context, metadata) == []
    finally:
        command.downgrade(alembic_config, "base")


def test_database_downgrade_preserves_roles_used_by_another_database(
    alembic_config: Config,
    database_url: str,
    second_database_url: str,
) -> None:
    """Rolling back one database leaves the other database's grants usable."""
    assert database_url != second_database_url
    second_engine = create_engine(second_database_url)
    try:
        with _database_url(database_url):
            command.upgrade(alembic_config, "head")
        with _database_url(second_database_url):
            command.upgrade(alembic_config, "head")

        with _database_url(database_url):
            command.downgrade(alembic_config, "base")

        with second_engine.connect() as connection, connection.begin():
            role_exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = 'counterparty_mcp'")
            ).scalar_one_or_none()
            assert role_exists == 1
            connection.execute(text("SET LOCAL ROLE counterparty_mcp"))
            connection.execute(text("SELECT count(*) FROM reports.report_snapshots"))

        with _database_url(database_url):
            command.upgrade(alembic_config, "head")
            command.downgrade(alembic_config, "base")
    finally:
        with _database_url(second_database_url):
            command.downgrade(alembic_config, "base")
        second_engine.dispose()


def test_run_revision_preserves_framework_tables(alembic_config: Config, engine: Engine) -> None:
    """App run rollback leaves library checkpoint tables in workspace untouched."""
    command.upgrade(alembic_config, "head")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE workspace.checkpoints (marker text)"))
            connection.execute(text("INSERT INTO workspace.checkpoints VALUES ('keep')"))
        command.downgrade(alembic_config, "0004")
        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT marker FROM workspace.checkpoints")) == "keep"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS workspace.checkpoints"))
        command.downgrade(alembic_config, "base")
