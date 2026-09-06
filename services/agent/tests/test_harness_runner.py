"""The harness publishes one run as the safe public projection (Specs 04 §8)."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from counterparty_contracts import ClientRequestId, ProjectId, RunId, RunStatus, ThreadId
from counterparty_storage import ThreadScope
from harness_fixtures import INN, PROCEEDS_REF, report_tools
from langchain_core.tools import BaseTool

from counterparty_agent.composition import select_runner
from counterparty_agent.config import AgentSettings
from counterparty_agent.harness import runner as runner_module
from counterparty_agent.harness.runner import ASSISTANT_MESSAGE_INDEX, create_harness_runner
from counterparty_agent.transport import (
    AppendItemOperation,
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


async def test_empty_persisted_project_returns_add_company_guidance_without_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing report pin is an unmet precondition, not a long model run."""
    from counterparty_agent.harness.prompts import ASK_TO_ADD_COMPANY

    def forbidden_tools(_settings: AgentSettings) -> None:
        raise AssertionError("No tools before a company is pinned")

    monkeypatch.setattr(runner_module, "reports_toolset", forbidden_tools)
    run = make_run("Check supplier")
    run.scope = ThreadScope(tenant_id=uuid4(), project_id=uuid4(), thread_id=uuid4())
    await create_harness_runner(SETTINGS)(RunContext(run))
    texts = [event.text for event in run.events if isinstance(event, AppendTextOperation)]
    assert texts == [ASK_TO_ADD_COMPANY]
    assert not [event for event in run.events if isinstance(event, TerminalError)]


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


async def test_each_tool_call_streams_its_own_activity_line() -> None:
    """The trail is one running-then-completed activity per tool the model calls."""
    run = make_run(f"What does the report say about {INN}?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    appended = [
        event.value
        for event in run.events
        if isinstance(event, AppendItemOperation) and event.path == ("activities",)
    ]
    from counterparty_agent.harness.prompts import TOOL_ACTIVITY

    items = [item for item in appended if isinstance(item, dict)]
    assert [item["label"] for item in items] == [
        TOOL_ACTIVITY["get_company_overview"][1],
        TOOL_ACTIVITY["get_report_section"][1],
    ]
    assert all(item["status"] == "running" for item in items)

    settled = {
        event.path[1]: event.value
        for event in run.events
        if isinstance(event, SetOperation)
        and event.path[:1] == ("activities",)
        and event.path[-1] == "status"
    }
    assert settled == {"0": "completed", "1": "completed"}


def test_a_citation_that_opens_a_line_is_moved_to_its_end() -> None:
    """A leading ``[evidence:X], fact`` becomes ``fact [evidence:X]``."""
    from counterparty_agent.harness.runner import _tidy_answer

    raw = "[evidence:report:r1:/finReports/0/common/profit], loss for 2025 was -28M."
    assert (
        _tidy_answer(raw)
        == "loss for 2025 was -28M. [evidence:report:r1:/finReports/0/common/profit]"
    )
    # A line that already ends with its citation is untouched.
    good = "Equity is negative [evidence:report:r1:/finReports/0/liabilities/capitals]."
    assert _tidy_answer(good) == good


def test_a_sentence_broken_across_lines_is_joined_back() -> None:
    """Orphan tails — ``. [ref]``, ``(2024) [ref]`` — rejoin the sentence above."""
    from counterparty_agent.harness.runner import _tidy_answer

    raw = "\n".join(
        [
            "Loss grew from -6M [evidence:report:r1:/finReports/1/common/profit]",
            "(2024) to -28M",
            ". [evidence:report:r1:/finReports/0/common/profit]",
        ]
    )
    assert _tidy_answer(raw) == (
        "Loss grew from -6M [evidence:report:r1:/finReports/1/common/profit] (2024) to -28M. "
        "[evidence:report:r1:/finReports/0/common/profit]"
    )
    # Two proper sentences stay on their own lines.
    two = (
        "Equity is negative [evidence:report:r1:/a].\n"
        "The report has no revenue [evidence:report:r1:/b]."
    )
    assert _tidy_answer(two) == two


async def test_a_turn_with_no_tool_calls_shows_no_activity_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn that never calls a tool leaves the activity list empty."""

    @asynccontextmanager
    async def no_tools(_settings: AgentSettings) -> AsyncIterator[Sequence[BaseTool]]:
        yield []

    monkeypatch.setattr(runner_module, "reports_toolset", no_tools)
    run = make_run("Hi, what can you help me with?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    assert not [
        event
        for event in run.events
        if isinstance(event, AppendItemOperation) and event.path == ("activities",)
    ]


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


async def test_a_grounded_answer_survives_the_mcp_content_block_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live MCP adapter returns text content blocks, not a JSON string.

    Both the deterministic model's tool-result parsing and the evidence ledger
    must read the envelope out of ``[{"type": "text", "text": "<json>"}]`` or
    every grounded line is dropped as unreferenced.
    """
    from counterparty_contracts import (
        CompanyOverviewEnvelope,
        McpStatus,
        ReportSectionEnvelope,
    )
    from harness_fixtures import REPORT_ID, company_overview, financials_section
    from langchain_core.tools import tool

    def blocks(payload: str) -> list[dict[str, str]]:
        return [{"type": "text", "text": payload}]

    @tool
    def get_company_overview(inn: str | None = None, report_id: str | None = None) -> object:
        """Identify one imported company."""
        return blocks(
            CompanyOverviewEnvelope(
                status=McpStatus.OK,
                data=company_overview(),
                source_report_ids=[REPORT_ID],
                rule_version="mcp-read-v1",
            ).model_dump_json()
        )

    @tool
    def get_report_section(report_id: str, section: str) -> object:
        """Inspect one section of a pinned report."""
        return blocks(
            ReportSectionEnvelope(
                status=McpStatus.OK,
                data=financials_section(),
                source_report_ids=[REPORT_ID],
                rule_version="mcp-read-v1",
            ).model_dump_json()
        )

    @asynccontextmanager
    async def toolset(_settings: AgentSettings) -> AsyncIterator[Sequence[BaseTool]]:
        yield [get_company_overview, get_report_section]

    monkeypatch.setattr(runner_module, "reports_toolset", toolset)
    run = make_run(f"Supplier {INN} asks for 80 percent upfront. What do the figures say?")
    await create_harness_runner(SETTINGS)(RunContext(run))

    answer = "".join(event.text for event in run.events if isinstance(event, AppendTextOperation))
    assert "[evidence:" in answer
    assert not [event for event in run.events if isinstance(event, TerminalError)]


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
