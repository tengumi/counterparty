"""Local boundary around the supported LangGraph PostgreSQL checkpointer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from counterparty_storage import ThreadScope
from counterparty_storage.repositories import AgentRunOwner
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo


class Checkpointer(Protocol):
    """Minimum checkpointer behavior currently used by the service shell."""

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete the checkpoints owned by one thread."""


@asynccontextmanager
async def postgres_checkpointer(dsn: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Open and close the official asynchronous PostgreSQL saver.

    Schema setup is intentionally excluded: migrations run as a deployment step,
    never once per application worker.
    """
    async with AsyncPostgresSaver.from_conn_string(workspace_conninfo(dsn)) as saver:
        yield saver


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
