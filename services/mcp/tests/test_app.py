"""Contract tests for the FastAPI/FastMCP shell."""

import httpx
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from counterparty_mcp.app import ServiceResources, app, mcp
from counterparty_mcp.models import McpStatus


async def test_health_and_async_cleanup() -> None:
    """The composed lifespan serves health and keeps owned resources open."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "mcp"}
        resources: ServiceResources = app.state.resources
        assert resources.closed is False


async def test_resources_are_closed_after_lifespan() -> None:
    """Shutdown reliably closes asynchronous service dependencies."""
    async with app.router.lifespan_context(app):
        resources: ServiceResources = app.state.resources
        assert resources.closed is False

    assert resources.closed is True


async def test_read_only_stub_is_discoverable_and_typed() -> None:
    """A standard MCP client can inspect and invoke the typed tool."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        overview_tool = next(tool for tool in tools if tool.name == "get_company_overview")
        result: CallToolResult = await client.call_tool(
            "get_company_overview", {"inn": "7449088645"}
        )

    assert overview_tool.annotations is not None
    assert overview_tool.annotations.readOnlyHint is True
    assert overview_tool.annotations.openWorldHint is False
    assert overview_tool.outputSchema is not None
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == McpStatus.UNAVAILABLE
    assert result.structured_content["data"]["lookup_inn"] == "7449088645"


async def test_stub_enforces_exactly_one_lookup_key() -> None:
    """Business validation distinguishes invalid input from protocol failure."""
    async with Client(mcp) as client:
        result = await client.call_tool("get_company_overview", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == McpStatus.UNAVAILABLE
    assert result.structured_content["errors"][0]["code"] == "validation_error"
