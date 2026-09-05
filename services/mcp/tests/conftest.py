"""Deterministic tool fixtures; HTTP transport remains the real MCP client."""

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from counterparty_contracts import (
    Activity,
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyStatusView,
    DisplayLevel,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    PageInfo,
    ReportId,
    ReportIdentity,
    ReportSection,
    ZskAssessment,
)

from counterparty_mcp.config import Settings

REPORT_ID = ReportId(UUID("11111111-1111-4111-8111-111111111111"))
COMPANY_ID = CompanyId(UUID("22222222-2222-4222-8222-222222222222"))
TEST_TOKEN = "synthetic-agent-credential-for-tests-only"


@pytest.fixture
def settings() -> Settings:
    """Provision the local test service with a synthetic credential digest."""
    return Settings(auth_token_sha256=hashlib.sha256(TEST_TOKEN.encode()).hexdigest())


class FixtureReader:
    """Controllable dependency for the service boundary and timeout tests."""

    def __init__(self) -> None:
        """Start with complete typed records of a synthetic imported company."""
        self.closed = False
        self.calls = 0
        self.delay = 0.0
        self.error: Exception | None = None
        self.record_text = "Synthetic activity"
        self.record_count = 105
        self.active_reads = 0
        self.max_active_reads = 0

    async def overview(self, request: GetCompanyOverviewInput) -> CompanyOverview | None:
        """Return a deterministic overview or simulate a missing report."""
        await self._wait()
        if request.inn == "0000000000":
            return None
        return CompanyOverview(
            company=CompanyIdentity(id=COMPANY_ID, inn="7449088645", short_name="Fixture"),
            report=ReportIdentity(
                id=REPORT_ID,
                source_report_at=datetime(2024, 1, 1, tzinfo=UTC),
                ingested_at=datetime(2024, 2, 1, tzinfo=UTC),
            ),
            status=CompanyStatusView(
                raw_value="ACTIVE", label="ACTIVE", availability=Availability.AVAILABLE
            ),
            bank_risk=BankRiskAssessment(
                raw_value="LOW",
                label="LOW",
                display_level=DisplayLevel.NEUTRAL,
                availability=Availability.AVAILABLE,
            ),
            zsk=ZskAssessment(
                raw_value="GREEN",
                display_level=DisplayLevel.POSITIVE,
                availability=Availability.AVAILABLE,
                policy_version="test-v1",
            ),
            rule_version="test-v1",
        )

    async def section(self, request: GetReportSectionInput) -> ReportSection | None:
        """Page typed activities by an offset; shared domain cursors have DB tests."""
        await self._wait()
        offset = int(request.cursor or "0")
        end = min(offset + request.limit, self.record_count)
        return ReportSection(
            report_id=request.report_id,
            section=request.section,
            availability=Availability.AVAILABLE,
            records=[
                Activity(
                    code=str(index),
                    description=self.record_text,
                    is_primary=index == 0,
                    evidence_refs=[f"report:{REPORT_ID}:/kindsOfActivityInfo/activities/{index}"],
                )
                for index in range(offset, end)
            ],
            page=PageInfo(
                limit=request.limit,
                has_more=end < self.record_count,
                next_cursor=str(end) if end < self.record_count else None,
            ),
            total_records=self.record_count,
            rule_version="test-v1",
        )

    async def _wait(self) -> None:
        self.calls += 1
        self.active_reads += 1
        self.max_active_reads = max(self.max_active_reads, self.active_reads)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error is not None:
                raise self.error
        finally:
            self.active_reads -= 1

    async def aclose(self) -> None:
        """Track the real lifespan shutdown."""
        self.closed = True


@pytest.fixture
def reader() -> FixtureReader:
    """Create an isolated fake reader for one test."""
    return FixtureReader()
