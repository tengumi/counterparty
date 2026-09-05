"""MCP tools reach the harness through the supported adapter (AG-03).

``langchain-mcp-adapters`` turns the internal reports MCP server into ordinary
LangChain tools, and Deep Agents routes calls to them through its own loop.
This service therefore contains no tool router, no protocol client and no
hand-written schema: whatever the server exposes is what the model may call,
which is also why a tool added later (``compare_companies``) needs no change
here.

The connection is server-side configuration. The model never sees the URL or
the service token, and it cannot name a different server.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection

from ..config import AgentSettings

REPORTS_SERVER = "reports"


def reports_connection(settings: AgentSettings) -> StreamableHttpConnection:
    """Describe the internal reports MCP endpoint for the adapter."""
    if settings.mcp_url is None:
        raise ValueError("AGENT_MCP_URL is not configured")
    headers: dict[str, str] = {}
    if settings.mcp_auth_token is not None:
        headers["Authorization"] = f"Bearer {settings.mcp_auth_token.get_secret_value()}"
    return StreamableHttpConnection(
        transport="streamable_http",
        url=settings.mcp_url,
        headers=headers or None,
        timeout=settings.mcp_timeout_seconds,
    )


@asynccontextmanager
async def reports_toolset(settings: AgentSettings) -> AsyncIterator[Sequence[BaseTool]]:
    """Yield the report tools, or nothing when no MCP endpoint is configured."""
    if settings.mcp_url is None:
        yield ()
        return
    client = MultiServerMCPClient({REPORTS_SERVER: reports_connection(settings)})
    yield await client.get_tools(server_name=REPORTS_SERVER)
