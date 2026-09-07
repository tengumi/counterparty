"""Deep Agents harness: model adapter, context, MCP tools and grounding.

Deep Agents is the agent harness, LangGraph holds state and drives execution,
and LangChain provides the model adapter. This package configures those three
and adds one boundary of its own: an answer whose factual claims do not resolve
to observed evidence never reaches the user.
"""

from .context import (
    AgentContext,
    CompanyContext,
    ContextSource,
    ProjectContext,
    ThreadContext,
    WorkspaceContextSource,
    build_context,
)
from .deterministic import DeterministicChatModel
from .evidence import (
    Claim,
    EvidenceResolver,
    RepairedAnswer,
    RunEvidenceLedger,
    ValidationReport,
    Violation,
    repair_answer,
    split_claims,
    validate_answer,
)
from .graph import CompiledHarness, TurnResult, create_harness, final_text, run_turn
from .knowledge import (
    REFERENCE,
    REFERENCE_VERSION,
    KnowledgeEntry,
    KnowledgeExample,
    lookup,
    render_reference,
    render_relevant,
)
from .middleware import EvidenceLedgerMiddleware
from .models import create_chat_model
from .runner import create_harness_runner
from .tools import reports_connection, reports_toolset

__all__ = [
    "REFERENCE",
    "REFERENCE_VERSION",
    "AgentContext",
    "Claim",
    "CompanyContext",
    "CompiledHarness",
    "ContextSource",
    "DeterministicChatModel",
    "EvidenceLedgerMiddleware",
    "EvidenceResolver",
    "KnowledgeEntry",
    "KnowledgeExample",
    "ProjectContext",
    "RepairedAnswer",
    "RunEvidenceLedger",
    "ThreadContext",
    "TurnResult",
    "ValidationReport",
    "Violation",
    "WorkspaceContextSource",
    "build_context",
    "create_chat_model",
    "create_harness",
    "create_harness_runner",
    "final_text",
    "lookup",
    "render_reference",
    "render_relevant",
    "repair_answer",
    "reports_connection",
    "reports_toolset",
    "run_turn",
    "split_claims",
    "validate_answer",
]
