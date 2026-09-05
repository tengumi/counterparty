"""Local boundary around the supported LangGraph PostgreSQL checkpointer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


class Checkpointer(Protocol):
    """Minimum checkpointer behavior currently used by the service shell."""

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete the checkpoints owned by one thread."""


@asynccontextmanager
async def postgres_checkpointer(dsn: str) -> AsyncIterator[Checkpointer]:
    """Open and close the official asynchronous PostgreSQL saver.

    Schema setup is intentionally excluded: migrations run as a deployment step,
    never once per application worker.
    """
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        yield saver
