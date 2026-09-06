"""Bridge between one agent run and the harness (Specs 04 §7, 10 §7).

The transport already owns run lifecycle, cancellation and delivery, so this
module only executes one turn inside it and publishes the safe projection:
an activity label, the answer text and a terminal status. Internal prompts,
raw tool arguments and the model's intermediate messages stay out of the
stream, as Specs 04 §8 requires.

What it does not do is decide *how* the turn runs. That belongs to the Deep
Agents graph built in :mod:`counterparty_agent.harness.graph`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from counterparty_contracts import RunStatus
from counterparty_storage import ThreadScope
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from ..config import AgentSettings
from ..transport.runs import RunContext
from .context import AgentContext, build_context
from .evidence import RunEvidenceLedger
from .graph import create_harness, run_turn
from .knowledge import lookup, render_relevant
from .models import create_chat_model
from .prompts import (
    ACTIVITY_CHECKING_CONTEXT,
    ACTIVITY_READING_REPORT,
    ASK_TO_ADD_COMPANY,
    RUN_FAILED_MESSAGE,
)
from .tools import reports_toolset

logger = logging.getLogger(__name__)

# The assistant message index of a run that starts from a fresh thread (one
# user message, no prior turns). ``_assistant_paths`` generalises it.
ASSISTANT_MESSAGE_INDEX = "1"


def _assistant_paths(state: object) -> tuple[str, str, tuple[str, ...]]:
    """Indices of the turn this run appends, given the state it starts from.

    The projection carries the whole thread (prior turns are seeded into
    ``initial_state``), so the run's own assistant message and activity land
    after whatever history is already there — not at a fixed ``1``/``0``.
    """
    messages = getattr(state, "messages", [])
    activities = getattr(state, "activities", [])
    msg_index = str(len(messages))
    act_index = str(len(activities))
    return msg_index, act_index, ("messages", msg_index, "blocks", "0", "text")

ContextLoader = Callable[[ThreadScope], Awaitable[AgentContext]]
ConfigFactory = Callable[[ThreadScope], Awaitable[RunnableConfig]]


async def default_context(scope: ThreadScope) -> AgentContext:
    """Build the minimum context for a process without a database.

    The project layer is thin rather than invented: the identifiers are real
    and the descriptive values stay empty. A process with a database uses
    :class:`~counterparty_agent.harness.context.WorkspaceContextSource`
    instead, which reads the authorized project and thread layers.
    """
    return build_context(
        project_id=scope.project_id,
        tenant_id=scope.tenant_id,
        title="",
        workflow_status="unknown",
        context_version=0,
        companies=[],
        thread_id=scope.thread_id,
        thread_title="",
        thread_status="active",
    )


async def default_config(scope: ThreadScope) -> RunnableConfig:
    """Key checkpoints by the thread id alone, for a process without a database.

    A process with a database uses
    :func:`counterparty_agent.checkpointing.checkpoint_config`, which derives
    the key from a server-authorized thread instead of a bare identifier.
    """
    return RunnableConfig(configurable={"thread_id": str(scope.thread_id)})


def create_harness_runner(
    settings: AgentSettings,
    *,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    context_loader: ContextLoader = default_context,
    config_factory: ConfigFactory = default_config,
) -> Callable[[RunContext], Awaitable[None]]:
    """Build the run function the transport registry executes."""
    model = create_chat_model(settings)

    async def run(ctx: RunContext) -> None:
        state = ctx.run.initial_state
        msg_index, act_index, text_path = _assistant_paths(state)
        started = _started_at(ctx)
        ctx.set(("run", "status"), RunStatus.RUNNING.value)
        ctx.append_item(
            ("activities",),
            {
                "id": f"activity-{msg_index}",
                "kind": "reading_report",
                "label": ACTIVITY_READING_REPORT,
                "status": "running",
                "evidence_refs": [],
                "started_at": started,
                "finished_at": None,
            },
        )
        ctx.append_item(
            ("messages",),
            {
                "id": f"assistant-{ctx.run.id}",
                "role": "assistant",
                "blocks": [{"type": "text", "text": ""}],
                "status": "streaming",
                "created_at": started,
            },
        )
        try:
            scope = ctx.scope or ThreadScope(
                tenant_id=UUID(int=0),
                project_id=UUID(str(state.project_id)),
                thread_id=UUID(str(state.thread_id)),
            )
            context = await context_loader(scope)
            config = await config_factory(scope)
            if ctx.scope is not None and not context.project.companies:
                ctx.set(("activities", act_index, "label"), ACTIVITY_CHECKING_CONTEXT)
                ctx.append_text(text_path, ASK_TO_ADD_COMPANY)
                _finish(
                    ctx,
                    status=RunStatus.COMPLETED,
                    message_status="complete",
                    refs=(),
                    msg_index=msg_index,
                    act_index=act_index,
                )
                return
            context = replace(context, relevant_notes=render_relevant(lookup(ctx.prompt)))
            # Specs 04 §3 caps tool calls per run; one model step per call plus
            # the final answer is the graph-level equivalent of that budget.
            config["recursion_limit"] = settings.max_tool_calls * 2 + 1
            ledger = RunEvidenceLedger()
            async with reports_toolset(settings) as tools:
                graph = create_harness(
                    model=model,
                    tools=tools,
                    context=context,
                    ledger=ledger,
                    checkpointer=checkpointer,
                )
                result = await asyncio.wait_for(
                    run_turn(graph, question=ctx.prompt, config=config, ledger=ledger),
                    timeout=settings.run_timeout_seconds,
                )
        except Exception:
            # CancelledError is a BaseException and stays with the registry.
            logger.exception("Harness run %s failed", ctx.run.id)
            _finish(
                ctx,
                status=RunStatus.FAILED,
                message_status="error",
                refs=(),
                msg_index=msg_index,
                act_index=act_index,
            )
            ctx.fail(RUN_FAILED_MESSAGE)
            return
        if ctx.cancel_requested:
            _finish(
                ctx,
                status=RunStatus.CANCELLED,
                message_status="partial",
                refs=(),
                msg_index=msg_index,
                act_index=act_index,
            )
            return
        ctx.append_text(text_path, result.answer)
        _finish(
            ctx,
            status=RunStatus.COMPLETED,
            message_status="complete",
            refs=result.observed_refs,
            msg_index=msg_index,
            act_index=act_index,
        )

    return run


def _started_at(ctx: RunContext) -> str:
    run_info = ctx.run.initial_state.run
    if run_info is None:  # pragma: no cover - runs always carry RunInfo
        return datetime.now(UTC).isoformat()
    return run_info.started_at.isoformat()


def _finish(
    ctx: RunContext,
    *,
    status: RunStatus,
    message_status: str,
    refs: tuple[str, ...],
    msg_index: str,
    act_index: str,
) -> None:
    finished = datetime.now(UTC).isoformat()
    ctx.set(
        ("activities", act_index, "status"),
        "completed" if refs or status is RunStatus.COMPLETED else "failed",
    )
    ctx.set(("activities", act_index, "finished_at"), finished)
    ctx.set(("activities", act_index, "evidence_refs"), list(refs))
    ctx.set(("messages", msg_index, "status"), message_status)
    ctx.set(("run", "status"), status.value)
    ctx.set(("run", "finished_at"), finished)
    ctx.set(("run", "last_public_revision"), 1)
    ctx.set(("revision",), 1)
    ctx.set(("save_status",), "saved")
