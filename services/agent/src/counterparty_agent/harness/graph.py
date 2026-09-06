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

import logging
import re
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
    CITATION,
    RunEvidenceLedger,
    ValidationReport,
    repair_answer,
)
from .filesystem import scoped_permissions
from .middleware import ActivityTraceMiddleware, EvidenceLedgerMiddleware, ToolTrace
from .prompts import CITE_INSTRUCTION, REPAIR_INSTRUCTION

logger = logging.getLogger(__name__)

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


_THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think(?:ing)?>.*$", re.IGNORECASE | re.DOTALL)
_THINK_HEAD = re.compile(r"^.*?</think(?:ing)?>", re.IGNORECASE | re.DOTALL)
# A model that reasons in-band often marks where the reply itself starts.
_ANSWER_MARKER = re.compile(
    r"(?:^|\n)\s*(?:итоговый |финальн(?:ый|ая) |краткий )?отв(?:ет|еть)\s*[:-]\s*",
    re.IGNORECASE,
)


def strip_reasoning(text: str) -> str:
    """Drop a model's in-band chain-of-thought from what the user will see.

    ``qwen*-noreason`` still narrates its deliberation inside the message body.
    Cut ``<think>`` blocks, and when the model flags its own reply with an
    "Ответ:" marker, keep only what follows the last one.
    """
    cleaned = _THINK_BLOCK.sub("", text)
    cleaned = _THINK_OPEN.sub("", cleaned)
    if "</think" in cleaned.lower():
        cleaned = _THINK_HEAD.sub("", cleaned)
    markers = list(_ANSWER_MARKER.finditer(cleaned))
    if markers:
        cleaned = cleaned[markers[-1].end() :]
    return cleaned.strip()


def final_text(messages: Sequence[BaseMessage]) -> str:
    """Return the text of the last assistant message of a turn, reasoning removed."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return strip_reasoning(str(message.text))
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
    history: Sequence[BaseMessage] = (),
    enforce_grounding: bool = True,
) -> TurnResult:
    """Run one turn and keep an ungrounded claim from leaving it.

    One model pass, then a deterministic, non-destructive grounding pass: a line
    that cites a dead reference is dropped, everything else is shown as written.
    There is no second model round — for the demo it roughly doubled the wait on
    a full company analysis and the weak model rarely improved the answer with
    it.

    ``history`` is the thread's earlier messages, passed in explicitly rather
    than left to the checkpointer to replay: the caller owns the durable
    conversation record and this keeps multi-turn context working even if a
    checkpoint write is lost. ``add_messages`` merges by id, so re-sending a
    message the checkpoint already holds is harmless.

    ``enforce_grounding=False`` is for turns that answer with a *definition*
    (what a report field means) rather than a fact about a company: there is
    nothing to cite and the grounding pass would wrongly strip the answer.
    """
    turn = [*history, HumanMessage(content=question)]
    state = await graph.ainvoke({"messages": turn}, config)
    answer = final_text(state["messages"])
    if not enforce_grounding:
        return TurnResult(
            answer=answer,
            model_repair_attempted=False,
            dropped_claims=(),
            observed_refs=tuple(ledger.known_refs()),
        )
    # The weak model routinely answers with facts and no citation at all even
    # though it just read the report. One targeted retry when the answer has
    # zero [evidence:] and the run did observe refs — nothing else is changed.
    refs = list(ledger.known_refs())
    cited = bool(CITATION.search(answer))
    attempted = bool(refs) and not cited
    if attempted:
        logger.info("run_turn: answer had no citation, %d refs available — retrying", len(refs))
        so_far = list(state["messages"])
        so_far.append(HumanMessage(content=CITE_INSTRUCTION.format(refs="\n".join(refs))))
        state = await graph.ainvoke({"messages": so_far}, config)
        answer = final_text(state["messages"])
        if not CITATION.search(answer):
            logger.warning("run_turn: retry still produced no citation")
    outcome = repair_answer(answer, ledger)
    return TurnResult(
        answer=outcome.text,
        model_repair_attempted=attempted,
        dropped_claims=outcome.dropped,
        observed_refs=tuple(ledger.known_refs()),
    )
