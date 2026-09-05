"""Alembic environment for the Counterparty Workspace schemas.

Two rules are enforced here rather than left to reviewer discipline:

* the database URL comes from the environment, never from ``alembic.ini``;
* only the schemas this project owns are ever compared or generated. Tables
  created by a framework in its own schema (for example LangGraph checkpoint
  storage, whose DDL belongs to the library and is applied as a separate
  deployment step) stay invisible to autogenerate, so a project revision can
  never propose dropping them.
"""

import os
from typing import Any

from alembic import context
from counterparty_storage import VERSION_TABLE_SCHEMA, target_metadata
from sqlalchemy import Connection, engine_from_config, pool, text

from schema_policy import include_name

config = context.config

DATABASE_URL_ENV = "COUNTERPARTY_DATABASE_URL"


def _database_url() -> str:
    """Resolve the database URL from ``-x database_url=`` or the environment."""
    override = context.get_x_argument(as_dictionary=True).get("database_url")
    url = override or os.environ.get(DATABASE_URL_ENV) or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            f"database URL is not configured: set {DATABASE_URL_ENV} "
            "or pass -x database_url=postgresql+psycopg://..."
        )
    return url


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without connecting to a database."""
    _configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_version_schema(connection: Connection) -> None:
    """Create the schema that holds the Alembic version table, if needed."""
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{VERSION_TABLE_SCHEMA}"'))


def run_migrations_online() -> None:
    """Run migrations against a live connection in one transaction."""
    section: dict[str, Any] = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _ensure_version_schema(connection)
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        # SQLAlchemy 2.0 connections roll back on close; commit explicitly so a
        # revision is never reported as applied while the DDL is discarded.
        connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
