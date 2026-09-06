"""Transport layer between the agent runtime and the web client.

Everything on the wire is produced by the supported ``assistant-stream``
encoder; this package only decides *what* public projection is published.
"""

from .durable import ActiveRunExists, DurableRuns
from .projection import fold_projection
from .public_state import (
    PublicActivity,
    PublicAgentState,
    PublicMessage,
    TextBlock,
    initial_state,
)
from .router import create_transport_router
from .runs import (
    AppendItemOperation,
    AppendTextOperation,
    Run,
    RunContext,
    RunEvent,
    RunRegistry,
    SetOperation,
    TerminalError,
)
from .stub_agent import Scenario, deterministic_agent

__all__ = [
    "ActiveRunExists",
    "AppendItemOperation",
    "AppendTextOperation",
    "DurableRuns",
    "PublicActivity",
    "PublicAgentState",
    "PublicMessage",
    "Run",
    "RunContext",
    "RunEvent",
    "RunRegistry",
    "Scenario",
    "SetOperation",
    "TerminalError",
    "TextBlock",
    "create_transport_router",
    "deterministic_agent",
    "fold_projection",
    "initial_state",
]
