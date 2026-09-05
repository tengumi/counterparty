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
from .filesystem import scoped_permissions, thread_workspace_root
from .graph import TurnResult, create_harness, final_text, run_turn
from .middleware import EvidenceLedgerMiddleware
from .models import create_chat_model
from .tools import reports_connection, reports_toolset

__all__ = [
    "AgentContext",
    "Claim",
    "CompanyContext",
    "ContextSource",
    "DeterministicChatModel",
    "EvidenceLedgerMiddleware",
    "EvidenceResolver",
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
    "final_text",
    "repair_answer",
    "reports_connection",
    "reports_toolset",
    "run_turn",
    "scoped_permissions",
    "split_claims",
    "thread_workspace_root",
    "validate_answer",
]
