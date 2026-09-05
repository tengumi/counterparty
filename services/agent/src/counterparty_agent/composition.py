"""Application-scoped resource composition for the agent service."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from counterparty_storage.repositories import AgentRunOwner
from fastapi import FastAPI

from .checkpointing import Checkpointer, postgres_checkpointer
from .config import AgentSettings
from .persistence import postgres_run_owner
from .transport import RunRegistry, deterministic_agent

CheckpointerFactory = Callable[[AgentRunOwner], AbstractAsyncContextManager[Checkpointer]]
RunOwnerFactory = Callable[[str], AbstractAsyncContextManager[AgentRunOwner]]


@dataclass(frozen=True, slots=True)
class AgentResources:
    """Resources shared for exactly one application lifespan."""

    checkpointer: Checkpointer | None
    runs: RunRegistry
    run_owner: AgentRunOwner | None = None


def create_lifespan(
    settings: AgentSettings,
    checkpointer_factory: CheckpointerFactory = postgres_checkpointer,
    run_owner_factory: RunOwnerFactory = postgres_run_owner,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build a FastAPI lifespan with injectable external-resource factories."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dsn = settings.postgres_dsn
        async with RunRegistry(deterministic_agent) as runs:
            app.state.runs = runs
            if dsn is None:
                app.state.resources = AgentResources(checkpointer=None, runs=runs)
                yield
                return

            async with (
                run_owner_factory(dsn.get_secret_value()) as owner,
                checkpointer_factory(owner) as checkpointer,
            ):
                app.state.resources = AgentResources(
                    checkpointer=checkpointer,
                    runs=runs,
                    run_owner=owner,
                )
                yield

    return lifespan
