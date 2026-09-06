"""Native PostgreSQL acceptance checks; only the explicitly disposable test DB is reset."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from conftest import COMPANY_ID, REPORT_ID
from counterparty_contracts import (
    Availability,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    ReportId,
    ReportSectionFilters,
    ReportSectionName,
)
from counterparty_domain.report_reads import ReportReadData
from counterparty_storage import create_database_engine, metadata
from counterparty_storage.reports.enums import IngestionStatus, SourceState
from counterparty_storage.reports.models import (
    Company,
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportBatch,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)
from counterparty_storage.roles import DatabaseRole, create_role_statements, grant_statements
from fastmcp import Client
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from test_app import http_transport

from counterparty_mcp.app import create_app
from counterparty_mcp.config import Settings
from counterparty_mcp.database import PostgreSQLReportReader
from counterparty_mcp.runtime import ServiceResources

pytestmark = pytest.mark.asyncio(loop_scope="module")
NEW_REPORT_ID = ReportId(uuid4())


@pytest.fixture(scope="module")
async def database() -> AsyncIterator[tuple[AsyncEngine, Settings]]:
    """Reset a disposable DB and provision a login inheriting only the MCP role."""
    url = os.environ.get("MCP_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("MCP_TEST_ADMIN_DATABASE_URL missing; PostgreSQL checks not executed")
    # The disposable role also works against the password-authenticated Compose DB.
    password = uuid4().hex
    engine = create_database_engine(url)
    async with engine.begin() as connection:
        for schema in ("reports", "workspace"):
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(metadata.create_all)
        for statement in create_role_statements() + grant_statements([DatabaseRole.MCP]):
            await connection.execute(text(statement))
        await connection.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles "
                "WHERE rolname = 'i2_mcp_reader_test') THEN "
                "CREATE ROLE i2_mcp_reader_test LOGIN; END IF; END $$"
            )
        )
        await connection.execute(text("GRANT counterparty_mcp TO i2_mcp_reader_test"))
        await connection.execute(text(f"ALTER ROLE i2_mcp_reader_test PASSWORD '{password}'"))
    async with AsyncSession(engine) as session, session.begin():
        batch_id = uuid4()
        session.add(
            ImportBatch(
                id=batch_id,
                file_name="synthetic-tool-test",
                sha256="a" * 64,
                parser_version="test-v1",
                record_count=2,
            )
        )
        session.add(Company(id=COMPANY_ID, inn="7449088645"))
        await session.flush()
        for report_id, year, name in [
            (REPORT_ID, 2024, "Old fixture"),
            (NEW_REPORT_ID, 2025, "Latest fixture"),
        ]:
            raw: dict[str, Any] = {
                "baseInfo": {"shortName": name, "riskLevel": "LOW"},
                "status": {"status": "ACTIVE"},
                "zskRiskLevel": "GREEN",
                "finReports": [
                    {
                        "common": {"year": 2023, "proceeds": 0, "profit": None},
                        "assets": {"totalAssets": "bad"},
                    }
                ],
                "executionProceedings": [
                    {"number": f"case-{index}", "amount": index, "active": index % 2 == 0}
                    for index in range(125)
                ],
                "licenses": [],
            }
            session.add(
                ReportSnapshot(
                    id=report_id,
                    company_id=COMPANY_ID,
                    batch_id=batch_id,
                    source_record_id=str(year),
                    source_record_jsonb={},
                    source_report_at=datetime(year, 1, 1, tzinfo=UTC),
                    # The older source arrives later: latest is not latest-ingested.
                    ingested_at=datetime(2030 if year == 2024 else 2026, 1, 1, tzinfo=UTC),
                    hash=str(year) * 16,
                    raw_jsonb=raw,
                    ingestion_status=IngestionStatus.COMPLETE,
                )
            )
            await session.flush()
            session.add(CompanyProfile(report_id=report_id, short_name=name, bank_risk_raw="LOW"))
            session.add(CompanyStatus(report_id=report_id, status_raw="ACTIVE"))
            session.add(
                ZskAssessment(
                    report_id=report_id,
                    raw_value="GREEN",
                    display_policy_version="test-v1",
                    source_path="/zskRiskLevel",
                )
            )
            session.add(
                FinancialStatement(
                    report_id=report_id,
                    year=2023,
                    ordinal=0,
                    proceeds=Decimal(0),
                    source_path="/finReports/0",
                )
            )
            for key, value in raw.items():
                session.add(
                    SectionAvailability(
                        report_id=report_id,
                        section=key,
                        source_state=SourceState.PRESENT_EMPTY
                        if value == []
                        else SourceState.PRESENT,
                        record_count=len(value) if isinstance(value, list) else 1,
                        source_path="/" + key,
                    )
                )
    login_url = make_url(url).set(username="i2_mcp_reader_test", password=password)
    settings = Settings(database_url=SecretStr(login_url.render_as_string(hide_password=False)))
    try:
        yield engine, settings
    finally:
        async with engine.begin() as connection:
            for schema in ("reports", "workspace"):
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def test_db_role_is_reports_only_and_transactions_are_read_only(
    database: tuple[AsyncEngine, Settings],
) -> None:
    """The actual login cannot read workspace or write reports, even if code attempts it."""
    _, settings = database
    reader = PostgreSQLReportReader(settings)
    try:
        async with reader.read_session() as session:
            assert (await session.execute(text("SHOW transaction_read_only"))).scalar_one() == "on"
            assert not (
                await session.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                )
            ).scalar_one()
        # A raw pool connection also lacks write grants: enforcement is not an annotation.
        for statement in [
            "SELECT * FROM workspace.projects LIMIT 1",
            "DELETE FROM reports.report_snapshots WHERE false",
            "UPDATE reports.companies SET inn=inn WHERE false",
            "INSERT INTO reports.companies (inn) VALUES ('0000000000')",
        ]:
            with pytest.raises(DBAPIError):
                async with reader.engine.begin() as connection:
                    await connection.execute(text(statement))
        async with reader.read_session() as session:
            assert (
                await session.execute(text("SELECT count(*) FROM reports.report_snapshots"))
            ).scalar_one() == 2
    finally:
        await reader.aclose()
    assert reader.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


async def test_source_date_resolution_and_pinned_snapshot(
    database: tuple[AsyncEngine, Settings],
) -> None:
    """Importing an old report later cannot change an explicitly pinned read."""
    _, settings = database
    reader = PostgreSQLReportReader(settings)
    try:
        latest = await reader.overview(GetCompanyOverviewInput(inn="7449088645"))
        pinned = await reader.overview(GetCompanyOverviewInput(report_id=REPORT_ID))
        assert latest is not None and pinned is not None
        assert latest.report.id == NEW_REPORT_ID
        assert latest.company.short_name == "Latest fixture"
        assert pinned.report.id == REPORT_ID
        assert pinned.company.short_name == "Old fixture"
        assert await reader.overview(GetCompanyOverviewInput(inn="0000000000")) is None
        assert await reader.overview(GetCompanyOverviewInput(report_id=ReportId(uuid4()))) is None
    finally:
        await reader.aclose()


async def test_standard_http_pagination_filters_and_invalid_cursor(
    database: tuple[AsyncEngine, Settings],
    settings: Settings,
) -> None:
    """A normal authenticated MCP client follows the shared cursor through 125 DB rows."""
    _, db_settings = database
    application = create_app(
        settings.model_copy(
            update={"database_url": db_settings.database_url, "max_response_bytes": 262144}
        )
    )
    async with (
        application.router.lifespan_context(application),
        Client(http_transport(application)) as client,
    ):
        args = {"report_id": str(REPORT_ID), "section": "execution_proceedings", "limit": 100}
        first = await client.call_tool("get_report_section", args)
        assert first.structured_content is not None
        page = first.structured_content["data"]
        assert len(page["records"]) == 100
        assert page["total_records"] == 125
        cursor = page["page"]["next_cursor"]
        second = await client.call_tool(
            "get_report_section", {**args, "cursor": cursor, "filters": {}}
        )
        assert second.structured_content is not None
        rest = second.structured_content["data"]
        assert len(rest["records"]) == 25
        assert rest["page"]["has_more"] is False
        refs = [row["evidence_refs"][0] for row in page["records"] + rest["records"]]
        assert len(set(refs)) == 125
        assert refs[0] == f"report:{REPORT_ID}:/executionProceedings/0"
        assert refs[-1] == f"report:{REPORT_ID}:/executionProceedings/124"
        assert page["records"][0]["amount"]["value"] == "0"
        changes: list[dict[str, Any]] = [
            {"filters": {"active": True}},
            {"report_id": str(NEW_REPORT_ID)},
            {"section": "licenses"},
            {"cursor": "not-a-cursor"},
        ]
        for changed in changes:
            invalid = await client.call_tool(
                "get_report_section", {**args, "cursor": cursor, **changed}
            )
            assert invalid.structured_content is not None
            assert invalid.structured_content["errors"][0]["code"] == "validation_error"
        filtered = await client.call_tool(
            "get_report_section", {**args, "filters": {"active": True}}
        )
        assert filtered.structured_content is not None
        assert filtered.structured_content["data"]["total_records"] == 63
        assert all(
            row["active"]["value"] is True for row in filtered.structured_content["data"]["records"]
        )


async def test_finance_missing_empty_invalid_zero_and_evidence(
    database: tuple[AsyncEngine, Settings],
) -> None:
    """Projection preserves normalized money and the exact reason for each non-value."""
    _, settings = database
    reader = PostgreSQLReportReader(settings)
    try:
        section = await reader.section(
            GetReportSectionInput(
                report_id=REPORT_ID,
                section=ReportSectionName.FINANCIALS,
                filters=ReportSectionFilters(years=[2023]),
            )
        )
        assert section is not None
        period = section.records[0]
        assert period.kind == "financial_period"
        assert period.proceeds.value == "0.00" and period.proceeds.currency == "RUB"
        assert period.proceeds.evidence_refs == [
            f"report:{REPORT_ID}:/finReports/0/common/proceeds"
        ]
        assert period.profit.availability is Availability.PRESENT_EMPTY
        assert period.equity.availability is Availability.MISSING
        assert period.total_assets.availability is Availability.INVALID
        assert period.proceeds.period == 2023
        for name, expected in [
            (ReportSectionName.LICENSES, Availability.PRESENT_EMPTY),
            (ReportSectionName.INSPECTIONS, Availability.MISSING),
        ]:
            result = await reader.section(GetReportSectionInput(report_id=REPORT_ID, section=name))
            assert result is not None and result.availability is expected
            assert result.warnings
    finally:
        await reader.aclose()


async def test_database_timeout_rolls_back_and_releases_the_connection(
    database: tuple[AsyncEngine, Settings],
) -> None:
    """Cancellation of an actual PostgreSQL query frees the pool for a next read."""

    class SlowReader(PostgreSQLReportReader):
        async def _load(self, session: AsyncSession, report_id: UUID) -> ReportReadData | None:
            await session.execute(text("SELECT pg_sleep(1)"))
            return await super()._load(session, report_id)

    _, db_settings = database
    settings = db_settings.model_copy(update={"read_timeout_seconds": 0.05})
    reader = SlowReader(settings)
    try:
        result = await ServiceResources(settings, reader).overview(
            GetCompanyOverviewInput(report_id=REPORT_ID)
        )
        assert result.errors[0].code == "timeout" and result.errors[0].retryable
        assert reader.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        async with reader.read_session() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await reader.aclose()
