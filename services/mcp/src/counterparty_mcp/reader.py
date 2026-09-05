"""Report reader boundary used by MCP tools and the PostgreSQL adapter."""

from collections.abc import Sequence
from typing import Protocol

from counterparty_contracts import (
    CompanyOverview,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    ReportId,
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

    async def overviews(self, report_ids: Sequence[ReportId]) -> list[CompanyOverview]:
        """Read the same projection for several pinned reports.

        Unknown ids are omitted rather than represented by a placeholder
        company, so a caller can tell which snapshots were actually read.
        """
        ...

    async def aclose(self) -> None:
        """Dispose resources on application shutdown."""
        ...
