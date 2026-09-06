"""Application-scoped resource composition for the agent service."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from counterparty_storage import create_database_engine, create_session_factory
from counterparty_storage.repositories import AgentRunOwner
from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .checkpointing import Checkpointer, checkpoint_config, postgres_checkpointer
from .config import AgentSettings
from .harness.context import WorkspaceContextSource
from .harness.runner import create_harness_runner
from .persistence import postgres_run_owner
from .transport import DurableRuns, RunContext, RunRegistry, deterministic_agent

CheckpointerFactory = Callable[[AgentRunOwner], AbstractAsyncContextManager[Checkpointer]]
RunOwnerFactory = Callable[[str], AbstractAsyncContextManager[AgentRunOwner]]
AgentRunner = Callable[[RunContext], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AgentResources:
    """Resources shared for exactly one application lifespan."""

    checkpointer: Checkpointer | None
    runs: RunRegistry
    run_owner: AgentRunOwner | None = None


def _async_dsn(dsn: str) -> str:
    """Point a plain DSN at the async psycopg driver without changing the target."""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def select_runner(
    settings: AgentSettings,
    checkpointer: Checkpointer | None,
    *,
    owner: AgentRunOwner | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AgentRunner:
    """Choose the Deep Agents harness, or the transport stub without MCP.

    The harness needs report tools to ground an answer, so a deployment that
    names no MCP endpoint keeps the deterministic transport stub instead of
    running an agent that could only answer ungrounded. When a database is
    configured, the harness reads the authorized project and thread layers and
    keys checkpoints by a server-verified thread rather than by a request value.
    """
    if settings.mcp_url is None:
        return deterministic_agent
    saver = checkpointer if isinstance(checkpointer, BaseCheckpointSaver) else None
    if owner is not None and session_factory is not None:
        return create_harness_runner(
            settings,
            checkpointer=saver,
            context_loader=WorkspaceContextSource(session_factory).load,
            config_factory=partial(checkpoint_config, owner),
        )
    return create_harness_runner(settings, checkpointer=saver)


def create_lifespan(
    settings: AgentSettings,
    checkpointer_factory: CheckpointerFactory = postgres_checkpointer,
    run_owner_factory: RunOwnerFactory = postgres_run_owner,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build a FastAPI lifespan with injectable external-resource factories."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        dsn = settings.postgres_dsn
        if dsn is None:
            async with RunRegistry(select_runner(settings, None)) as runs:
                app.state.runs = runs
                app.state.resources = AgentResources(checkpointer=None, runs=runs)
                yield
            return

        engine = create_database_engine(_async_dsn(dsn.get_secret_value()), pool_size=2)
        try:
            session_factory = create_session_factory(engine)
            async with (
                run_owner_factory(dsn.get_secret_value()) as owner,
                checkpointer_factory(owner) as checkpointer,
                RunRegistry(
                    select_runner(
                        settings,
                        checkpointer,
                        owner=owner,
                        session_factory=session_factory,
                    ),
                    durable=DurableRuns(owner),
                ) as runs,
            ):
                app.state.runs = runs
                app.state.resources = AgentResources(
                    checkpointer=checkpointer,
                    runs=runs,
                    run_owner=owner,
                )
                yield
        finally:
            await engine.dispose()

    return lifespan
