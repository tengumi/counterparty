"""The database connection this process owns.

The engine is created once, at startup, and disposed of at shutdown. Nothing
here runs at import time, and no handler creates a connection of its own: a
request draws a session from the factory built here and gives it back when the
response leaves.

The URL names the ``counterparty_ui_api`` role. That role reads both schemas
and writes only ``workspace``; the provided report is not writable from this
service, and none of the code below tries to widen that.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from counterparty_storage import create_database_engine, create_session_factory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["SessionFactory", "open_database"]

SessionFactory = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def open_database(url: str, *, pool_size: int = 5) -> AsyncIterator[SessionFactory]:
    """Open the engine of one process and dispose of it on the way out.

    Args:
        url: Async PostgreSQL URL of the ``counterparty_ui_api`` role.
        pool_size: Connections this process keeps open.

    Yields:
        The session factory built from the engine.
    """
    engine = create_database_engine(url, pool_size=pool_size)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
