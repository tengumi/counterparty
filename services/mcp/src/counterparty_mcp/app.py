"""FastAPI and FastMCP composition root for read-only report tools."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from counterparty_contracts import ErrorCode
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import CompanyOverviewEnvelope, CompanyOverviewStub, McpStatus, ToolError


class ServiceResources:
    """Own resources that later revisions replace with reports-only adapters."""

    def __init__(self) -> None:
        """Create an open resource owner."""
        self.closed = False

    async def aclose(self) -> None:
        """Close owned asynchronous resources exactly once."""
        self.closed = True


@asynccontextmanager
async def service_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage process resources independently from individual MCP sessions."""
    resources = ServiceResources()
    _app.state.resources = resources
    try:
        yield
    finally:
        await resources.aclose()


mcp = FastMCP(
    "Counterparty Reports",
    instructions="Read-only access to imported contractor report snapshots.",
)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get company overview",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_company_overview(
    inn: Annotated[str | None, Field(pattern=r"^\d{10}(?:\d{2})?$")] = None,
    report_id: UUID | None = None,
) -> CompanyOverviewEnvelope:
    """Resolve one imported company by exactly one INN or report ID.

    Use this before reading report sections. Do not use it for external company
    search. The shell intentionally returns unavailable until the reports-only
    repository is connected; unknown identifiers will later return not_found.

    Examples: ``{"inn": "7449088645"}`` or
    ``{"report_id": "de305d54-75b4-431b-adb2-eb6b9e546014"}``.
    """
    if (inn is None) == (report_id is None):
        return CompanyOverviewEnvelope(
            status=McpStatus.UNAVAILABLE,
            errors=[
                ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Provide exactly one of inn or report_id.",
                )
            ],
        )

    return CompanyOverviewEnvelope(
        status=McpStatus.UNAVAILABLE,
        data=CompanyOverviewStub(lookup_inn=inn, lookup_report_id=report_id),
        errors=[
            ToolError(
                code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                message="Reports repository is not connected in the F0 shell.",
                retryable=True,
            )
        ],
    )


mcp_app = mcp.http_app(path="/mcp", stateless_http=True)
app = FastAPI(
    title="Counterparty MCP",
    version="0.1.0",
    lifespan=combine_lifespans(service_lifespan, mcp_app.lifespan),
)


@app.get("/healthz", tags=["operations"])
async def healthz() -> dict[str, str]:
    """Report process liveness without touching report data."""
    return {"status": "ok", "service": "mcp"}


app.mount("/", mcp_app)
