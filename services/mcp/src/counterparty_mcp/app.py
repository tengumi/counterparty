"""FastAPI and FastMCP composition root for authenticated read-only report tools."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    CompanyOverviewEnvelope,
    ErrorCode,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    McpStatus,
    ReportId,
    ReportSectionEnvelope,
    ReportSectionFilters,
    ReportSectionName,
    ToolError,
)
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from .auth import ServiceTokenVerifier
from .config import Settings
from .reader import ReportReader
from .runtime import ServiceResources

_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def create_app(settings: Settings | None = None, *, reader: ReportReader | None = None) -> FastAPI:
    """Compose a process; resources open only inside the application lifespan."""
    settings = settings or Settings.from_env()
    resources = ServiceResources(settings, reader)
    server = FastMCP(
        "Counterparty Reports",
        instructions=(
            "Read-only access to imported snapshots. Pin report_id from overview. "
            "Partial, missing and present_empty do not mean no risk; values retain their sources."
        ),
        auth=ServiceTokenVerifier(settings.auth_token_sha256),
        mask_error_details=True,
    )

    @server.tool(annotations=_ANNOTATIONS)
    async def get_company_overview(
        inn: Annotated[str | None, Field(pattern=r"^\d{10}(?:\d{2})?$", max_length=12)] = None,
        report_id: UUID | None = None,
    ) -> CompanyOverviewEnvelope:
        """Identify one imported company and choose sections to inspect.

        Supply exactly one INN or report_id. INN selects the latest source-dated
        snapshot; pin its returned report.id for all following calls. This tool
        does not search external registries and does not rank companies. Money
        is RUB decimal strings; facts name their own financial periods.

        Unknown company: not_found; incomplete source: partial; store outage or
        timeout: unavailable with a retryable error. For details and continuation
        use get_report_section. Examples: {"inn":"7449088645"} or
        {"report_id":"de305d54-75b4-431b-adb2-eb6b9e546014"}.
        """
        try:
            request = GetCompanyOverviewInput(
                inn=inn, report_id=ReportId(report_id) if report_id is not None else None
            )
        except ValidationError:
            return CompanyOverviewEnvelope(
                status=McpStatus.UNAVAILABLE,
                errors=[
                    ToolError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Provide exactly one of inn or report_id.",
                    )
                ],
                rule_version="mcp-read-v1",
            )
        return await resources.overview(request)

    @server.tool(annotations=_ANNOTATIONS)
    async def get_report_section(
        report_id: UUID,
        section: ReportSectionName,
        filters: ReportSectionFilters | None = None,
        cursor: Annotated[str | None, Field(min_length=1, max_length=4096)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> ReportSectionEnvelope:
        """Inspect facts and sources of one section of a pinned imported report.

        Use the report_id from overview, never INN here. The section enum is a
        whitelist; financials/coefficients/procurements accept years,
        execution_proceedings accepts active, arbitration accepts years, role,
        status_raw (the exact source token). Other sections accept no filters.
        SQL, expressions and URLs are not inputs. Money is RUB decimal strings,
        and source periods are explicit; arbitration records are aggregates.

        limit defaults to 20 and cannot exceed 100. has_more/next_cursor and
        result_truncated describe continuation: reuse the same report, section
        and filters. Missing/empty is source availability, never a risk verdict.
        Invalid filter/cursor, not_found, timeout and unavailable are distinct
        failures. Examples: {"report_id":"de305d54-75b4-431b-adb2-eb6b9e546014",
        "section":"financials","filters":{"years":[2023]}}; same report with
        section="execution_proceedings", filters={"active":true}, limit=20.
        """
        try:
            request = GetReportSectionInput(
                report_id=ReportId(report_id),
                section=section,
                filters=filters,
                cursor=cursor,
                limit=limit,
            )
        except ValidationError:
            return ReportSectionEnvelope(
                status=McpStatus.UNAVAILABLE,
                errors=[
                    ToolError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="One or more filters are not supported by this section.",
                    )
                ],
                rule_version="mcp-read-v1",
            )
        return await resources.section(request)

    @asynccontextmanager
    async def service_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if resources.reader is None and settings.database_url is not None:
            from .database import PostgreSQLReportReader

            resources.reader = PostgreSQLReportReader(settings)
        try:
            yield
        finally:
            await resources.aclose()

    mcp_app = server.http_app(path="/mcp", stateless_http=True)
    application = FastAPI(
        title="Counterparty MCP",
        version="0.1.0",
        lifespan=combine_lifespans(service_lifespan, mcp_app.lifespan),
    )
    application.state.resources = resources
    application.state.mcp = server

    @application.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        """Report process liveness without exposing credentials or opening data."""
        return {"status": "ok", "service": "mcp"}

    application.mount("/", mcp_app)
    return application


app = create_app()
mcp: FastMCP = app.state.mcp
