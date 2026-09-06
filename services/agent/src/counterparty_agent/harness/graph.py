"""Assembly of the Deep Agents harness (AG-01, AG-03).

Deep Agents is the harness, LangGraph holds the state and drives execution, and
LangChain supplies the model adapter. This module wires the three together and
adds nothing that resembles an agent loop, a tool router or a checkpoint
engine: ``create_deep_agent`` receives the model, the MCP tools, the assembled
system prompt, the scoped filesystem permissions and the existing PostgreSQL
checkpointer, and returns the compiled graph.

One graph is built per turn on purpose. Its filesystem permissions and its
evidence ledger both belong to a single ``(project_id, thread_id)`` pair, so a
graph shared between threads would blur exactly the boundary the service is
supposed to keep. Conversation state is not rebuilt with it: that lives in the
checkpoint keyed by the thread.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from .context import AgentContext
from .evidence import (
    RunEvidenceLedger,
    ValidationReport,
    repair_answer,
    validate_answer,
)
from .filesystem import scoped_permissions
from .middleware import ActivityTraceMiddleware, EvidenceLedgerMiddleware, ToolTrace
from .prompts import REPAIR_INSTRUCTION

CompiledHarness = CompiledStateGraph[Any, Any, Any, Any]
"""The compiled LangGraph the harness runs. Its generics are library detail."""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """One completed turn, after grounding was enforced."""

    answer: str
    """Text that may be published: every factual claim in it resolves."""

    model_repair_attempted: bool
    dropped_claims: tuple[str, ...]
    observed_refs: tuple[str, ...]

    @property
    def grounded(self) -> bool:
        """Whether the model produced a grounded answer without deletion."""
        return not self.dropped_claims


def create_harness(
    *,
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    context: AgentContext,
    ledger: RunEvidenceLedger,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    trace: ToolTrace | None = None,
) -> CompiledHarness:
    """Build the compiled Deep Agents graph for one thread."""
    middleware: list[Any] = [EvidenceLedgerMiddleware(ledger)]
    if trace is not None:
        middleware.append(ActivityTraceMiddleware(trace))
    graph: CompiledHarness = create_deep_agent(
        model=model,
        tools=list(tools),
        system_prompt=context.render(),
        middleware=middleware,
        permissions=scoped_permissions(context.project.project_id, context.thread.thread_id),
        backend=StateBackend(),
        checkpointer=checkpointer,
    )
    return graph


def final_text(messages: Sequence[BaseMessage]) -> str:
    """Return the text of the last assistant message of a turn."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return str(message.text)
    return ""


def _repair_prompt(report: ValidationReport, ledger: RunEvidenceLedger) -> str:
    claims = "\n".join(f"- {violation.claim}" for violation in report.violations)
    refs = "\n".join(f"- {ref}" for ref in ledger.known_refs()) or "-"
    return REPAIR_INSTRUCTION.format(claims=claims, refs=refs)


async def run_turn(
    graph: CompiledHarness,
    *,
    question: str,
    config: RunnableConfig,
    ledger: RunEvidenceLedger,
) -> TurnResult:
    """Run one turn and let no ungrounded claim out of it.

    The model gets exactly one chance to add the references it left out; the
    second pass is deterministic and simply removes what is still ungrounded.
    A repair turn is an ordinary turn of the same graph and thread, not a
    private loop: it is checkpointed like any other message.
    """
    state = await graph.ainvoke({"messages": [HumanMessage(content=question)]}, config)
    answer = final_text(state["messages"])
    report = validate_answer(answer, ledger)
    repaired = False
    if not report.ok:
        repaired = True
        state = await graph.ainvoke(
            {"messages": [HumanMessage(content=_repair_prompt(report, ledger))]}, config
        )
        answer = final_text(state["messages"])
    outcome = repair_answer(answer, ledger)
    return TurnResult(
        answer=outcome.text,
        model_repair_attempted=repaired,
        dropped_claims=outcome.dropped,
        observed_refs=tuple(ledger.known_refs()),
    )
