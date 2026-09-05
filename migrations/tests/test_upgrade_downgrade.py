"""End-to-end migration checks against a real PostgreSQL."""

from alembic import command
from alembic.config import Config
from counterparty_storage import REPORTS_SCHEMA, WORKSPACE_SCHEMA, metadata
from sqlalchemy import Engine, inspect, text

EXPECTED_TABLES = {table.name for table in metadata.sorted_tables}


def _schemas(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT schema_name FROM information_schema.schemata"))
        return {row[0] for row in rows}


def test_upgrade_creates_both_schemas_and_the_first_vertical(
    alembic_config: Config, engine: Engine
) -> None:
    """Upgrading to head builds exactly the mapped tables inside the reports schema."""
    command.upgrade(alembic_config, "head")
    try:
        assert {REPORTS_SCHEMA, WORKSPACE_SCHEMA} <= _schemas(engine)
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema=REPORTS_SCHEMA)) == EXPECTED_TABLES
        assert inspector.get_table_names(schema=WORKSPACE_SCHEMA) == []
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
        assert set(inspect(engine).get_table_names(schema=REPORTS_SCHEMA)) == EXPECTED_TABLES
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
