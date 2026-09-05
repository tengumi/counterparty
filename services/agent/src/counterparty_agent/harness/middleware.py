"""Harness middleware that records what the tools actually returned.

Grounding needs to know which evidence references exist. The supported place
to see every tool result is ``AgentMiddleware.wrap_tool_call``; using it keeps
tool dispatch inside Deep Agents instead of behind a router of our own.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from .evidence import RunEvidenceLedger

try:  # pragma: no cover - import path differs between langchain 1.x patch releases
    from langchain.agents.middleware.types import ToolCallRequest
except ImportError:  # pragma: no cover
    ToolCallRequest = Any  # type: ignore[assignment, misc]


class EvidenceLedgerMiddleware(AgentMiddleware[Any, Any]):
    """Record every evidence reference a tool result carried in this run."""

    name = "EvidenceLedgerMiddleware"

    def __init__(self, ledger: RunEvidenceLedger) -> None:
        """Bind the middleware to the ledger of exactly one run."""
        super().__init__()
        self.ledger = ledger

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Observe a synchronous tool result without changing it."""
        result = handler(request)
        self._observe(result)
        return result

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Observe an asynchronous tool result without changing it."""
        result = await handler(request)
        self._observe(result)
        return result

    def _observe(self, result: ToolMessage | Command[Any]) -> None:
        if isinstance(result, ToolMessage):
            self.ledger.observe(result.content)
            return
        update = getattr(result, "update", None)
        if isinstance(update, dict):
            for message in update.get("messages", []):
                if isinstance(message, ToolMessage):
                    self.ledger.observe(message.content)
