"""Explicit deployment command for the official saver tables in workspace.

Run after Alembic using a schema-owner DSN in AGENT_POSTGRES_DSN:
``uv run python -m counterparty_agent.deploy_checkpoints``.
Worker startup must never call this command or ``setup``.
"""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from .checkpointing import workspace_conninfo
from .config import AgentSettings

CHECKPOINT_TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)
_DEPLOY_LOCK = 1129337424


async def deploy_checkpoints(dsn: str) -> None:
    """Run library-owned migrations once under a deployment advisory lock."""
    async with await AsyncConnection.connect(
        workspace_conninfo(dsn),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT to_regnamespace('workspace') AS schema")
            row = await cursor.fetchone()
            if row is None or row["schema"] is None:
                raise RuntimeError("workspace is missing; run Alembic migrations first")
            await cursor.execute("SELECT pg_advisory_lock(%s)", (_DEPLOY_LOCK,))
        try:
            await AsyncPostgresSaver(connection).setup()
            async with connection.cursor() as cursor:
                for table in CHECKPOINT_TABLES:
                    privileges = (
                        "SELECT"
                        if table == "checkpoint_migrations"
                        else "SELECT, INSERT, UPDATE, DELETE"
                    )
                    await cursor.execute(
                        sql.SQL("GRANT {} ON TABLE workspace.{} TO counterparty_agent").format(
                            sql.SQL(privileges), sql.Identifier(table)
                        )
                    )
        finally:
            await connection.execute("SELECT pg_advisory_unlock(%s)", (_DEPLOY_LOCK,))


def main() -> None:
    """Deploy from backend configuration without printing database credentials."""
    dsn = AgentSettings().postgres_dsn
    if dsn is None:
        raise SystemExit("AGENT_POSTGRES_DSN is required")
    asyncio.run(deploy_checkpoints(dsn.get_secret_value()))
    print("Workspace checkpoint tables are ready.")


if __name__ == "__main__":
    main()
