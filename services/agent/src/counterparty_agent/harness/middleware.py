"""Harness middleware that records what the tools actually returned.

Grounding needs to know which evidence references exist. The supported place
to see every tool result is ``AgentMiddleware.wrap_tool_call``; using it keeps
tool dispatch inside Deep Agents instead of behind a router of our own.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from .evidence import RunEvidenceLedger

try:  # pragma: no cover - import path differs between langchain 1.x patch releases
    from langchain.agents.middleware.types import ToolCallRequest
except ImportError:  # pragma: no cover
    ToolCallRequest = Any  # type: ignore[assignment, misc]


class ToolTrace(Protocol):
    """Sink that turns each tool call into a streamed activity line."""

    def begin(self, tool_name: str) -> object:
        """Open an activity for a starting tool call; return its handle."""
        ...

    def finish(self, handle: object, *, ok: bool) -> None:
        """Close the activity opened for a finished tool call."""
        ...


def _tool_name(request: Any) -> str:
    """Best-effort tool name from a middleware request across langchain patches."""
    call = getattr(request, "tool_call", None)
    if isinstance(call, dict):
        name = call.get("name")
        if isinstance(name, str):
            return name
    tool_name = getattr(getattr(request, "tool", None), "name", None)
    return tool_name if isinstance(tool_name, str) else "tool"


class ActivityTraceMiddleware(AgentMiddleware[Any, Any]):
    """Publish one running/finished activity per tool call, nothing more.

    The tool arguments and results never reach the sink; only the tool name is
    used, and it is mapped to a human label upstream. This is the observable
    trail the run shows while it works — not a second tool router.
    """

    name = "ActivityTraceMiddleware"

    def __init__(self, trace: ToolTrace) -> None:
        """Bind the middleware to the activity sink of one run."""
        super().__init__()
        self.trace = trace

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Bracket a synchronous tool call with an activity."""
        handle = self.trace.begin(_tool_name(request))
        ok = False
        try:
            result = handler(request)
            ok = True
            return result
        finally:
            self.trace.finish(handle, ok=ok)

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Bracket an asynchronous tool call with an activity."""
        handle = self.trace.begin(_tool_name(request))
        ok = False
        try:
            result = await handler(request)
            ok = True
            return result
        finally:
            self.trace.finish(handle, ok=ok)


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
