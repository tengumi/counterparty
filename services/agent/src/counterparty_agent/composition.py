"""Application-scoped resource composition for the agent service."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from .checkpointing import Checkpointer, postgres_checkpointer
from .config import AgentSettings

CheckpointerFactory = Callable[[str], AbstractAsyncContextManager[Checkpointer]]


@dataclass(frozen=True, slots=True)
class AgentResources:
    """Resources shared for exactly one application lifespan."""

    checkpointer: Checkpointer | None


def create_lifespan(
    settings: AgentSettings,
    checkpointer_factory: CheckpointerFactory = postgres_checkpointer,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build a FastAPI lifespan with injectable external-resource factories."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dsn = settings.postgres_dsn
        if dsn is None:
            app.state.resources = AgentResources(checkpointer=None)
            yield
            return

        async with checkpointer_factory(dsn.get_secret_value()) as checkpointer:
            app.state.resources = AgentResources(checkpointer=checkpointer)
            yield

    return lifespan
