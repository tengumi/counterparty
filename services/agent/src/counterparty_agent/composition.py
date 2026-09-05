"""Application-scoped resource composition for the agent service."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from counterparty_storage.repositories import AgentRunOwner
from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver

from .checkpointing import Checkpointer, postgres_checkpointer
from .config import AgentSettings
from .harness.runner import create_harness_runner
from .persistence import postgres_run_owner
from .transport import RunContext, RunRegistry, deterministic_agent

CheckpointerFactory = Callable[[AgentRunOwner], AbstractAsyncContextManager[Checkpointer]]
RunOwnerFactory = Callable[[str], AbstractAsyncContextManager[AgentRunOwner]]
AgentRunner = Callable[[RunContext], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AgentResources:
    """Resources shared for exactly one application lifespan."""

    checkpointer: Checkpointer | None
    runs: RunRegistry
    run_owner: AgentRunOwner | None = None


def select_runner(settings: AgentSettings, checkpointer: Checkpointer | None) -> AgentRunner:
    """Choose the Deep Agents harness, or the transport stub without MCP.

    The harness needs report tools to ground an answer, so a deployment that
    names no MCP endpoint keeps the deterministic transport stub instead of
    running an agent that could only answer ungrounded.
    """
    if settings.mcp_url is None:
        return deterministic_agent
    saver = checkpointer if isinstance(checkpointer, BaseCheckpointSaver) else None
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

        async with (
            run_owner_factory(dsn.get_secret_value()) as owner,
            checkpointer_factory(owner) as checkpointer,
            RunRegistry(select_runner(settings, checkpointer)) as runs,
        ):
            app.state.runs = runs
            app.state.resources = AgentResources(
                checkpointer=checkpointer,
                runs=runs,
                run_owner=owner,
            )
            yield

    return lifespan
