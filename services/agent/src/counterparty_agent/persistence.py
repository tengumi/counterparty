"""Bounded single-worker PostgreSQL lifecycle for the persistence spike.

This is infrastructure for a future durable run registry. The V01 transport
registry remains a separate, explicitly in-memory spike.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from counterparty_storage import create_database_engine
from counterparty_storage.repositories import AgentRunOwner, agent_run_owner


@asynccontextmanager
async def postgres_run_owner(dsn: str) -> AsyncIterator[AgentRunOwner]:
    """Acquire ownership before recovery and persist interruption on shutdown."""
    engine = create_database_engine(dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        async with agent_run_owner(engine) as owner:
            await owner.interrupt_active()
            try:
                yield owner
            finally:
                await owner.interrupt_active(only_current=True)
    finally:
        await engine.dispose()
