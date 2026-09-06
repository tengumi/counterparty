"""Creating the async engine and handing out units of work.

Nothing here runs at import time. A service calls :func:`create_database_engine`
once during startup, keeps the returned engine for its lifetime and disposes of
it on shutdown; a shared package must not decide when a process opens a socket.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .access import TenantScope
from .unit_of_work import AsyncUnitOfWork

__all__ = ["create_database_engine", "create_session_factory", "unit_of_work"]


def create_database_engine(url: str, *, echo: bool = False, pool_size: int = 5) -> AsyncEngine:
    """Create the engine one service uses for the whole of its lifetime.

    Args:
        url: An async PostgreSQL URL, for example ``postgresql+psycopg://``.
        echo: Whether to log SQL. Left off by default: statements can carry
            user content, which does not belong in logs.
        pool_size: Connections kept open per process.
    """
    return create_async_engine(url, echo=echo, pool_size=pool_size, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory a request handler draws sessions from."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def unit_of_work(
    session_factory: async_sessionmaker[AsyncSession], scope: TenantScope
) -> AsyncIterator[AsyncUnitOfWork]:
    """Open one transaction for one tenant.

    The block rolls back unless it commits, so an interrupted handler leaves no
    partially written project behind.
    """
    async with session_factory() as session:
        uow = AsyncUnitOfWork(session, scope)
        async with uow:
            yield uow
