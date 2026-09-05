"""Read-only PostgreSQL adapter over the reports schema and shared projections."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from counterparty_contracts import (
    CompanyOverview,
    ContractWarning,
    GetCompanyOverviewInput,
    GetReportSectionInput,
    ReportSection,
    WarningCode,
)
from counterparty_domain.report_reads import ReportReadData, build_company_overview
from counterparty_domain.report_sections import build_report_section
from counterparty_storage import create_database_engine, create_session_factory
from counterparty_storage.reports.models import ImportWarning, ReportsBase
from counterparty_storage.repositories.reports import (
    CompanyReadRepository,
    ReportSnapshotReadRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings


class PostgreSQLReportReader:
    """Load stored source values in a database-enforced read-only transaction.

    Deployment grants the login only counterparty_mcp. No migration, tenant
    context, workspace repository or schema bootstrap belongs to this adapter.
    """

    def __init__(self, settings: Settings) -> None:
        """Create owned pooling resources; the first read opens a connection."""
        if settings.database_url is None:
            raise ValueError("MCP_DATABASE_URL is required for PostgreSQL reads")
        self.engine = create_database_engine(
            settings.database_url.get_secret_value(), pool_size=settings.max_concurrent_reads
        )
        self._sessions = create_session_factory(self.engine)
        self._statement_timeout_ms = max(1, int(settings.read_timeout_seconds * 1000))

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        """Start a read-only transaction before any lookup can execute SQL."""
        async with self._sessions() as session, session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": str(self._statement_timeout_ms)},
            )
            yield session

    async def overview(self, request: GetCompanyOverviewInput) -> CompanyOverview | None:
        """Resolve INN by source date, or read exactly the requested report id."""
        async with self.read_session() as session:
            report_id: UUID | None = request.report_id
            if report_id is None:
                assert request.inn is not None
                company = await CompanyReadRepository(session).get_by_inn(request.inn)
                snapshot = (
                    await ReportSnapshotReadRepository(session).latest_for_company(company.id)
                    if company is not None
                    else None
                )
                report_id = snapshot.id if snapshot is not None else None
            if report_id is None:
                return None
            data = await self._load(session, report_id)
        return build_company_overview(data) if data is not None else None

    async def section(self, request: GetReportSectionInput) -> ReportSection | None:
        """Read typed facts and records of one immutable snapshot."""
        async with self.read_session() as session:
            data = await self._load(session, request.report_id)
        return build_report_section(data, request) if data is not None else None

    async def _load(self, session: AsyncSession, report_id: UUID) -> ReportReadData | None:
        bundles = await ReportSnapshotReadRepository(session).get_read_bundles([report_id])
        if not bundles:
            return None
        bundle = bundles[0]
        snapshot, company = bundle.snapshot, bundle.company
        return ReportReadData(
            report_id=snapshot.id,
            company_id=company.id,
            inn=company.inn,
            ogrn=company.ogrn,
            source_report_at=snapshot.source_report_at,
            ingested_at=snapshot.ingested_at,
            raw=snapshot.raw_jsonb,
            ingestion_status=snapshot.ingestion_status.value,
            profile=_columns(bundle.profile),
            status=_columns(bundle.status),
            zsk=_columns(bundle.zsk),
            financials=[_columns(item) for item in bundle.financials],
            sections={item.section: _columns(item) for item in bundle.sections},
            warnings=[_warning(item) for item in bundle.warnings],
        )

    async def aclose(self) -> None:
        """Release all owned database pool resources at shutdown."""
        await self.engine.dispose()


def _columns(row: ReportsBase | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _warning(row: ImportWarning) -> ContractWarning:
    try:
        code = WarningCode(row.code)
    except ValueError:
        code = WarningCode.UNSPECIFIED
    return ContractWarning(code=code, message=row.message, source_path=row.source_path)
