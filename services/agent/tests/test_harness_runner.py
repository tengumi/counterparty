"""The harness publishes one run as the safe public projection (Specs 04 §8)."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from counterparty_contracts import ClientRequestId, ProjectId, RunId, RunStatus, ThreadId
from harness_fixtures import INN, PROCEEDS_REF, report_tools
from langchain_core.tools import BaseTool

from counterparty_agent.composition import select_runner
from counterparty_agent.config import AgentSettings
from counterparty_agent.harness import runner as runner_module
from counterparty_agent.harness.runner import ASSISTANT_MESSAGE_INDEX, create_harness_runner
from counterparty_agent.transport import (
    AppendTextOperation,
    PublicMessage,
    Run,
    RunContext,
    SetOperation,
    TerminalError,
    TextBlock,
    initial_state,
)

SETTINGS = AgentSettings(mcp_url="http://mcp.internal/mcp")


@pytest.fixture(autouse=True)
def stub_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the MCP connection with the accepted tool envelopes."""

    @asynccontextmanager
    async def toolset(_settings: AgentSettings) -> AsyncIterator[Sequence[BaseTool]]:
        yield report_tools()

    monkeypatch.setattr(runner_module, "reports_toolset", toolset)


def make_run(prompt: str) -> Run:
    """Build one accepted run with its initial public projection."""
    run_id = RunId(uuid4())
    now = datetime.now(UTC)
    return Run(
        id=run_id,
        client_request_id=ClientRequestId(uuid4()),
        initial_state=initial_state(
            project_id=ProjectId(uuid4()),
            thread_id=ThreadId(uuid4()),
            run_id=run_id,
            started_at=now,
            user_message=PublicMessage(
                id="user-1",
                role="user",
                blocks=[TextBlock(text=prompt)],
                status="complete",
                created_at=now,
            ),
        ),
        prompt=prompt,
    )


async def test_a_run_publishes_a_grounded_answer_and_completes() -> None:
    """A run publishes a grounded answer and completes."""
    run = make_run(f"Supplier {INN} asks for 80 percent upfront. What do the figures say?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    texts = [event.text for event in run.events if isinstance(event, AppendTextOperation)]
    statuses = [
        event.value
        for event in run.events
        if isinstance(event, SetOperation) and event.path == ("run", "status")
    ]
    assert f"[evidence:{PROCEEDS_REF}]" in "".join(texts)
    assert statuses[-1] == RunStatus.COMPLETED.value
    assert not [event for event in run.events if isinstance(event, TerminalError)]


async def test_the_activity_carries_the_refs_the_tools_returned() -> None:
    """The activity carries the refs the tools returned."""
    run = make_run(f"What does the report say about {INN}?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    refs = [
        event.value
        for event in run.events
        if isinstance(event, SetOperation) and event.path == ("activities", "0", "evidence_refs")
    ]
    assert refs
    published = refs[-1]
    assert isinstance(published, list)
    assert PROCEEDS_REF in published


async def test_a_failing_turn_ends_with_a_safe_terminal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing turn ends with a safe terminal error."""

    @asynccontextmanager
    async def broken(_settings: AgentSettings) -> AsyncIterator[Sequence[BaseTool]]:
        raise RuntimeError("postgres://user:secret@host/db is unreachable")
        yield ()

    monkeypatch.setattr(runner_module, "reports_toolset", broken)
    run = make_run("Anything?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    errors = [event for event in run.events if isinstance(event, TerminalError)]
    assert errors and "secret" not in errors[0].message
    message_status = [
        event.value
        for event in run.events
        if isinstance(event, SetOperation)
        and event.path == ("messages", ASSISTANT_MESSAGE_INDEX, "status")
    ]
    assert message_status[-1] == "error"


def test_without_mcp_the_transport_stub_stays_in_place() -> None:
    """Without MCP the transport stub stays in place."""
    from counterparty_agent.transport import deterministic_agent

    assert select_runner(AgentSettings(), None) is deterministic_agent


def test_with_mcp_the_harness_runs_the_thread() -> None:
    """With MCP the harness runs the thread."""
    from counterparty_agent.transport import deterministic_agent

    assert select_runner(SETTINGS, None) is not deterministic_agent


async def test_the_runner_passes_the_runs_trusted_scope_to_the_loaders() -> None:
    """The harness loads context and keys checkpoints from ``ctx.scope``."""
    from counterparty_storage import ThreadScope
    from langchain_core.runnables import RunnableConfig

    from counterparty_agent.harness.context import AgentContext
    from counterparty_agent.harness.runner import default_config, default_context

    seen: dict[str, ThreadScope] = {}

    async def context_loader(scope: ThreadScope) -> AgentContext:
        seen["context"] = scope
        return await default_context(scope)

    async def config_factory(scope: ThreadScope) -> RunnableConfig:
        seen["config"] = scope
        return await default_config(scope)

    scope = ThreadScope(tenant_id=uuid4(), project_id=uuid4(), thread_id=uuid4())
    run = make_run("Anything grounded?")
    run.scope = scope
    await create_harness_runner(
        SETTINGS, context_loader=context_loader, config_factory=config_factory
    )(RunContext(run))

    assert seen["context"] is scope
    assert seen["config"] is scope
