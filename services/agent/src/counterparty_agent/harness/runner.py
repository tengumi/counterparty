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
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from itertools import count
from uuid import UUID

from counterparty_contracts import RunStatus
from counterparty_storage import ThreadScope
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError

from ..config import AgentSettings
from ..transport.public_state import PublicMessage
from ..transport.runs import RunContext
from .client_profile import load_client_profile
from .context import AgentContext, build_context
from .evidence import RunEvidenceLedger
from .graph import create_harness, run_turn
from .indicator_guide import explain_indicator
from .knowledge import lookup, render_relevant
from .models import create_chat_model
from .profile import configure_harness_profile
from .prompts import (
    ASK_TO_ADD_COMPANY,
    DEFAULT_TOOL_ACTIVITY,
    EXPLAIN_TOOL_DESCRIPTION,
    RUN_FAILED_MESSAGE,
    SECTION_ACTIVITY,
    STEP_BUDGET_MESSAGE,
    TOOL_ACTIVITY,
)
from .provisioning import build_add_company_tool
from .tools import reports_toolset

logger = logging.getLogger(__name__)

_INN = re.compile(r"(?<![\dA-Fa-f-])(\d{10}|\d{12})(?![\dA-Fa-f-])")
"""An INN in free text, never a digit run inside a UUID."""

_EXPLAIN = re.compile(
    r"что\s+(?:\S+\s+){0,3}(?:такое|значит|означа|показыва|за\b)|"
    r"о\s*ч[её]м|про\s+что|как\s+(?:читать|понимать|это)|объясни|расшифру|"
    r"чем\s+отлича|зачем\s+нужн|это\s+(?:вообще\s+)?что",
    re.IGNORECASE,
)
"""A "what does this field/signal mean" question — pull the guide in front of
the model. It is only a hint now: a miss just means the guide is not
pre-injected; the model can still call ``explain_indicator`` itself."""

_WANTS_CHECK = re.compile(
    r"провер|разбер|оцен|контрагент|поставщик|покупател|подрядчик|надёжн|надежн|"
    r"стоит\s+ли\s+(?:работать|иметь\s+дело)",
    re.IGNORECASE,
)
"""The message asks to check a company. Without an INN and with an empty
project that is the one case worth answering with "назовите ИНН" instead of a
model run; a greeting or a general question goes to the model."""


def _is_explain(prompt: str) -> bool:
    return _INN.search(prompt) is None and _EXPLAIN.search(prompt) is not None


_HISTORY_MESSAGES = 10
"""How many earlier messages of the thread to replay to the model.

The checkpointer keeps state *inside* one turn's tool loop reliably; its
cross-turn message reload is not something we depend on. The durable record is
the stored public projection (AG-07), so the runner passes the thread's earlier
messages to the model itself. That is what lets the agent hold a conversation --
remember the deal terms, answer "что мы обсуждали" -- rather than meeting every
message cold.
"""


def _history_messages(prior: list[PublicMessage]) -> list[BaseMessage]:
    """Turn the projection's earlier messages into model input, newest window."""
    out: list[BaseMessage] = []
    for message in prior[-_HISTORY_MESSAGES:]:
        text = "\n".join(
            block.text for block in message.blocks if getattr(block, "text", "")
        ).strip()
        if not text:
            continue
        if message.role == "assistant":
            out.append(AIMessage(content=text, id=message.id))
        else:
            out.append(HumanMessage(content=text, id=message.id))
    return out


@tool("explain_indicator", description=EXPLAIN_TOOL_DESCRIPTION)
def _explain_indicator_tool(query: str) -> str:
    return explain_indicator(query)


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


class _ActivityStream:
    """Publish one activity line per tool call the model makes.

    Each ``begin``/``finish`` pair is a running-then-settled activity in the
    projection. The stream owns only the ``activities`` list from ``base``
    onward, so seeded history above it is never touched.
    """

    def __init__(self, ctx: RunContext, *, base: int, run_id: str) -> None:
        self._ctx = ctx
        self._base = base
        self._run_id = run_id
        self._next = count(base)
        self._open: list[int] = []
        self.count = 0

    def begin(self, tool_name: str, args: dict[str, object] | None = None) -> int:
        """Append a running activity for a starting tool call."""
        kind, label = TOOL_ACTIVITY.get(tool_name, DEFAULT_TOOL_ACTIVITY)
        if tool_name == "get_report_section":
            section = str((args or {}).get("section", "")).strip().lower()
            label = SECTION_ACTIVITY.get(section, label)
        index = next(self._next)
        now = datetime.now(UTC).isoformat()
        self._ctx.append_item(
            ("activities",),
            {
                "id": f"activity-{index}",
                "run_id": self._run_id,
                "kind": kind,
                "label": label,
                "status": "running",
                "evidence_refs": [],
                "started_at": now,
                "finished_at": None,
            },
        )
        self._open.append(index)
        self.count += 1
        return index

    def finish(self, handle: object, *, ok: bool) -> None:
        """Settle the activity opened for a finished tool call."""
        if not isinstance(handle, int):  # pragma: no cover - defensive
            return
        self._settle(handle, "completed" if ok else "failed")
        if handle in self._open:
            self._open.remove(handle)

    def close(self, *, ok: bool, refs: tuple[str, ...]) -> None:
        """Settle anything still running and attach the run's refs to the trail."""
        for index in list(self._open):
            self._settle(index, "completed" if ok else "failed")
        self._open.clear()
        if self.count and refs:
            self._ctx.set(("activities", str(self._base), "evidence_refs"), list(refs))

    def _settle(self, index: int, status: str) -> None:
        self._ctx.set(("activities", str(index), "status"), status)
        self._ctx.set(("activities", str(index), "finished_at"), datetime.now(UTC).isoformat())


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
    configure_harness_profile(settings)
    model = create_chat_model(settings)

    async def run(ctx: RunContext) -> None:
        state = ctx.run.initial_state
        history = _history_messages(list(state.messages)[:-1])
        msg_index, act_index, text_path = _assistant_paths(state)
        started = _started_at(ctx)
        stream = _ActivityStream(ctx, base=int(act_index), run_id=str(ctx.run.id))
        explains = _is_explain(ctx.prompt)
        ctx.set(("run", "status"), RunStatus.RUNNING.value)
        # No activity is seeded: the trail is what the model's tool calls
        # stream. A turn that answers from the dialogue alone shows none.
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
            can_add = (
                ctx.scope is not None
                and settings.ui_api_url is not None
                and settings.ui_api_internal_token is not None
            )
            no_company = ctx.scope is not None and not context.project.companies
            if no_company and _INN.search(ctx.prompt) is None and _WANTS_CHECK.search(ctx.prompt):
                # Asked to check a company but gave no INN, and nothing is pinned:
                # ask for the INN, no model run. A greeting, a definition question
                # or anything else goes to the model. When an INN *is* present the
                # model pins it itself with add_company_to_check.
                ctx.append_text(text_path, ASK_TO_ADD_COMPANY)
                _finish(
                    ctx,
                    status=RunStatus.COMPLETED,
                    message_status="complete",
                    refs=(),
                    msg_index=msg_index,
                    stream=stream,
                )
                return
            context = replace(
                context,
                client=load_client_profile(settings.client_profile_json),
                relevant_notes=render_relevant(lookup(ctx.prompt)),
            )
            # Specs 04 §3 caps tool calls per run; one model step per call plus
            # the final answer is the graph-level equivalent of that budget.
            config["recursion_limit"] = settings.max_tool_calls * 2 + 1

            question = ctx.prompt
            if not explains:
                # Freshest position in the context: the model mirrors its own
                # earlier uncited answers otherwise.
                question = (
                    f"{ctx.prompt}\n\n"
                    "(Открывай нужные разделы отчёта инструментами и каждый "
                    "конкретный факт или число о компании в ответе снабжай "
                    "ссылкой [evidence:<id>] из результата инструмента, в конце "
                    "предложения.)"
                )
            if explains:
                # Put the guide in front of the model and show the step, so the
                # answer visibly comes from the справочник, not the model's memory.
                handle = stream.begin("explain_indicator", {})
                guide = explain_indicator(ctx.prompt)
                stream.finish(handle, ok=True)
                question = (
                    f"Справочник показателей:\n{guide}\n\n"
                    f"Вопрос: {ctx.prompt}\n\n"
                    "Ответь пользователю коротко: 3–5 предложений, простыми словами, "
                    "только суть из справочника выше. Не описывай ход мыслей, не пиши "
                    "«Ответ:», без Markdown, без ссылок [evidence:...]. Инструменты не "
                    "вызывай — всё нужное уже дано."
                )

            ledger = RunEvidenceLedger()
            async with reports_toolset(settings) as report_tools:
                # On an explain turn the guide is already in the prompt; leaving
                # explain_indicator in the toolset just makes the model call it
                # again and again.
                tools: list[BaseTool] = list(report_tools)
                if not explains:
                    tools.append(_explain_indicator_tool)
                if can_add and ctx.scope is not None:
                    tools.append(build_add_company_tool(settings, project_id=ctx.scope.project_id))
                graph = create_harness(
                    model=model,
                    tools=tools,
                    context=context,
                    ledger=ledger,
                    checkpointer=checkpointer,
                    trace=stream,
                )
                result = await asyncio.wait_for(
                    run_turn(
                        graph,
                        question=question,
                        config=config,
                        ledger=ledger,
                        history=history,
                        enforce_grounding=not explains,
                    ),
                    timeout=settings.run_timeout_seconds,
                )
        except (GraphRecursionError, TimeoutError):
            # The model spent its whole tool budget without settling on an
            # answer. That is not a crash: keep the thread usable and say so,
            # rather than failing the run and leaving a blank chat.
            logger.warning("Harness run %s hit its step/time budget", ctx.run.id)
            ctx.append_text(text_path, STEP_BUDGET_MESSAGE)
            _finish(
                ctx,
                status=RunStatus.COMPLETED,
                message_status="partial",
                refs=(),
                msg_index=msg_index,
                stream=stream,
            )
            return
        except Exception:
            # CancelledError is a BaseException and stays with the registry.
            logger.exception("Harness run %s failed", ctx.run.id)
            _finish(
                ctx,
                status=RunStatus.FAILED,
                message_status="error",
                refs=(),
                msg_index=msg_index,
                stream=stream,
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
                stream=stream,
            )
            return
        answer = _tidy_answer(result.answer)
        if explains:
            answer = _clamp_definition(answer)
        ctx.append_text(text_path, answer)
        _finish(
            ctx,
            status=RunStatus.COMPLETED,
            message_status="complete",
            refs=result.observed_refs,
            msg_index=msg_index,
            stream=stream,
        )

    return run


# The model sometimes writes "[evidence: report:… ]" with stray spaces around
# the ref; normalise so both the frontend chip regex and the grounding check
# see a clean "[evidence:<ref>]".
_LOOSE_EVIDENCE = re.compile(r"\[\s*evidence:\s*([^\]\s]+)\s*\]")
# A raw ref id the model pasted as visible text instead of an [evidence:…] chip
# — with any wrapping parens/semicolon. It must never reach the user as text.
_BARE_REF = re.compile(r"[;,]?\s*\(?\s*(?<!evidence:)report:[0-9A-Fa-f-]{6,}:/[^\s)\]]+\)?")

_LEADING_REFS = re.compile(r"^\s*((?:\[evidence:[^\]]+\]\s*,?\s*)+)")
# A line that is really the tail of the previous sentence, broken off by the
# model: it opens with closing punctuation, a bare ``(2024)``-style
# parenthetical, or a citation.
_ORPHAN_TAIL = re.compile(r"^\s*(?:[.,;:)]|\(\d{4}\)|\[evidence:)")


def _tidy_answer(text: str) -> str:
    """Undo two things models do to a clean answer.

    A citation is moved from the start of a line to its end (some models emit
    ``[evidence:X], <fact>``). And a line that is only the broken-off tail of
    the sentence above it — opening with ``.``/``)``/``(2024)`` — is joined
    back onto that sentence instead of standing as its own fragment.
    """
    text = _LOOSE_EVIDENCE.sub(r"[evidence:\1]", text)
    text = _BARE_REF.sub("", text)
    joined: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if joined and line.strip() and _ORPHAN_TAIL.match(line):
            sep = "" if line.lstrip()[0] in ".,;:)" else " "
            joined[-1] = f"{joined[-1].rstrip()}{sep}{line.lstrip()}"
            continue
        joined.append(line)

    out: list[str] = []
    for line in joined:
        match = _LEADING_REFS.match(line)
        rest = line[match.end() :].strip().rstrip(",").strip() if match else ""
        if match and rest:
            refs = " ".join(re.findall(r"\[evidence:[^\]]+\]", match.group(1)))
            out.append(f"{rest} {refs}")
        else:
            out.append(line)
    return "\n".join(out)


_DEFINITION_LIMIT = 900


def _clamp_definition(text: str) -> str:
    """Keep an "объясни показатель" reply short even if the model over-answers.

    A definition needs a few sentences, not a page. Past the limit, cut back to
    the last sentence boundary that fits.
    """
    if len(text) <= _DEFINITION_LIMIT:
        return text
    head = text[:_DEFINITION_LIMIT]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "), head.rfind("\n"))
    return (head[: cut + 1] if cut > 200 else head).strip()


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
    stream: _ActivityStream,
) -> None:
    finished = datetime.now(UTC).isoformat()
    stream.close(ok=status is RunStatus.COMPLETED, refs=refs)
    ctx.set(("messages", msg_index, "status"), message_status)
    ctx.set(("run", "status"), status.value)
    ctx.set(("run", "finished_at"), finished)
    ctx.set(("run", "last_public_revision"), 1)
    ctx.set(("revision",), 1)
    ctx.set(("save_status",), "saved")
