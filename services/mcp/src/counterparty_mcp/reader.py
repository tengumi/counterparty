"""Report reader boundary used by MCP tools and the PostgreSQL adapter."""

from typing import Protocol

from counterparty_contracts import (
    CompanyOverview,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    ReportSection,
)


class ReportReader(Protocol):
    """Read projections from the imported corpus, never from workspace."""

    async def overview(self, request: GetCompanyOverviewInput) -> CompanyOverview | None:
        """Resolve a snapshot, or return None if it does not exist."""
        ...

    async def section(self, request: GetReportSectionInput) -> ReportSection | None:
        """Read a bounded section of one pinned report, or return None."""
        ...

    async def aclose(self) -> None:
        """Dispose resources on application shutdown."""
        ...
