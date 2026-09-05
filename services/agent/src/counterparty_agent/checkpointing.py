"""Local boundary around the supported LangGraph PostgreSQL checkpointer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from counterparty_storage import ThreadScope
from counterparty_storage.repositories import AgentRunOwner
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, AsyncCursor
from psycopg.conninfo import make_conninfo
from psycopg.rows import DictRow


class Checkpointer(Protocol):
    """Minimum checkpointer behavior currently used by the service shell."""

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete the checkpoints owned by one thread."""


class OwnedPostgresSaver(AsyncPostgresSaver):
    """Native saver with every cursor fenced by its physical connection owner.

    Only the cursor lifecycle is adapted; SQL, pipeline handling, serialization
    and checkpoint algorithms belong to langgraph-checkpoint-postgres 3.1.2.
    Its protected _cursor hook is version-sensitive and covered by native tests.
    """

    def __init__(self, owner: AgentRunOwner, connection: AsyncConnection[Any]) -> None:
        """Bind the native saver to the dedicated owner connection, never a pool."""
        super().__init__(connection)
        self._owner = owner
        self._closed = False

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[AsyncCursor[DictRow]]:
        if self._closed:
            raise RuntimeError("checkpoint saver lifetime has ended")
        async with (
            self._owner.transaction_connection(),
            super()._cursor(pipeline=pipeline) as cursor,
        ):
            yield cursor


@asynccontextmanager
async def postgres_checkpointer(owner: AgentRunOwner) -> AsyncIterator[AsyncPostgresSaver]:
    """Use the live owner's physical connection; deployment alone runs setup."""
    async with owner.transaction_connection() as connection:
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        if not isinstance(driver, AsyncConnection):
            raise TypeError("the checkpoint owner requires the psycopg async driver")
        driver.prepare_threshold = 0
        # Schema placement is local to this dedicated connection. No DDL runs.
        await driver.execute("SET search_path TO workspace, pg_catalog")
        saver = OwnedPostgresSaver(owner, driver)
    try:
        yield saver
    finally:
        saver._closed = True


def workspace_conninfo(dsn: str) -> str:
    """Pin unqualified saver SQL to workspace, overriding any caller search_path."""
    return make_conninfo(dsn, options="-csearch_path=workspace,pg_catalog")


async def checkpoint_config(owner: AgentRunOwner, scope: ThreadScope) -> RunnableConfig:
    """Resolve a server-authorized thread before deriving its stable saver key.

    No browser-provided state or checkpoint namespace is accepted. The full
    trusted scope is part of the mapping, even though thread UUIDs are unique.
    """
    async with owner.runs(scope) as repository:
        thread = await repository.require_thread()
        key = uuid5(
            NAMESPACE_URL, f"counterparty:{thread.tenant_id}:{thread.project_id}:{thread.id}"
        )
        return {"configurable": {"thread_id": str(key)}}
