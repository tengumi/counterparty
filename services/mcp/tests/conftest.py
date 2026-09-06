"""Deterministic tool fixtures; HTTP transport remains the real MCP client."""

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
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
    FactValue,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    PageInfo,
    ReportId,
    ReportIdentity,
    ReportSection,
    ValueType,
    ZskAssessment,
)

from counterparty_mcp.config import Settings

REPORT_ID = ReportId(UUID("11111111-1111-4111-8111-111111111111"))
COMPANY_ID = CompanyId(UUID("22222222-2222-4222-8222-222222222222"))
PEER_REPORT_ID = ReportId(UUID("33333333-3333-4333-8333-333333333333"))
PEER_COMPANY_ID = CompanyId(UUID("44444444-4444-4444-8444-444444444444"))
ABSENT_REPORT_ID = ReportId(UUID("55555555-5555-4555-8555-555555555555"))
TEST_TOKEN = "synthetic-agent-credential-for-tests-only"


@pytest.fixture
def settings() -> Settings:
    """Provision the local test service with a synthetic credential digest."""
    return Settings(auth_token_sha256=hashlib.sha256(TEST_TOKEN.encode()).hexdigest())


def _overview(
    report_id: ReportId,
    company_id: CompanyId,
    inn: str,
    name: str,
    *,
    revenue: Decimal | None,
) -> CompanyOverview:
    """Build one synthetic projection; a missing revenue leaves the cell unknown."""
    return CompanyOverview(
        company=CompanyIdentity(id=company_id, inn=inn, short_name=name),
        report=ReportIdentity(
            id=report_id,
            source_report_at=datetime(2024, 1, 1, tzinfo=UTC),
            ingested_at=datetime(2024, 2, 1, tzinfo=UTC),
        ),
        status=CompanyStatusView(
            raw_value="ACTIVE",
            label="ACTIVE",
            availability=Availability.AVAILABLE,
            evidence_refs=[f"report:{report_id}:/status/value"],
        ),
        bank_risk=BankRiskAssessment(
            raw_value="LOW",
            label="LOW",
            display_level=DisplayLevel.NEUTRAL,
            availability=Availability.AVAILABLE,
            evidence_refs=[f"report:{report_id}:/bankRisk/value"],
        ),
        zsk=ZskAssessment(
            raw_value="GREEN",
            display_level=DisplayLevel.POSITIVE,
            availability=Availability.AVAILABLE,
            policy_version="test-v1",
        ),
        facts=[
            FactValue(
                key="financials.2023.revenue",
                label="Выручка",
                value=str(revenue),
                value_type=ValueType.DECIMAL,
                period=2023,
                availability=Availability.AVAILABLE,
                evidence_refs=[f"report:{report_id}:/finance/2023/revenue"],
            )
        ]
        if revenue is not None
        else [],
        rule_version="test-v1",
    )


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
        self.facts_only = False
        self.active_reads = 0
        self.max_active_reads = 0
        self.peer_financials_missing = False

    async def overview(self, request: GetCompanyOverviewInput) -> CompanyOverview | None:
        """Return a deterministic overview or simulate a missing report."""
        await self._wait()
        if request.inn == "0000000000":
            return None
        return _overview(REPORT_ID, COMPANY_ID, "7449088645", "Fixture", revenue=Decimal("100"))

    async def overviews(self, report_ids: Sequence[ReportId]) -> list[CompanyOverview]:
        """Return one projection per known report; an unknown id has no row."""
        await self._wait()
        known = {
            REPORT_ID: _overview(
                REPORT_ID, COMPANY_ID, "7449088645", "Fixture", revenue=Decimal("100")
            ),
            PEER_REPORT_ID: _overview(
                PEER_REPORT_ID,
                PEER_COMPANY_ID,
                "1684017097",
                "Peer",
                revenue=None if self.peer_financials_missing else Decimal("250"),
            ),
        }
        return [known[report_id] for report_id in report_ids if report_id in known]

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
            ]
            if not self.facts_only
            else [],
            facts=[
                FactValue(
                    key=f"contact-{index}",
                    label="Contact",
                    value=self.record_text,
                    value_type=ValueType.STRING,
                    availability=Availability.AVAILABLE,
                    evidence_refs=[f"report:{REPORT_ID}:/contacts/{index}"],
                )
                for index in range(offset, end)
            ]
            if self.facts_only
            else [],
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
