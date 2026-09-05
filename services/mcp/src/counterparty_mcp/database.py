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
from counterparty_storage.reports.models import (
    Company,
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportWarning,
    ReportsBase,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)
from sqlalchemy import select, text
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
                report_id = (
                    await session.execute(
                        select(ReportSnapshot.id)
                        .join(Company, Company.id == ReportSnapshot.company_id)
                        .where(Company.inn == request.inn)
                        .order_by(
                            ReportSnapshot.source_report_at.desc(),
                            ReportSnapshot.ingested_at.desc(),
                            ReportSnapshot.id.desc(),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
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
        base_row = (
            await session.execute(
                select(ReportSnapshot, Company, CompanyProfile, CompanyStatus, ZskAssessment)
                .join(Company, Company.id == ReportSnapshot.company_id)
                .outerjoin(CompanyProfile, CompanyProfile.report_id == ReportSnapshot.id)
                .outerjoin(CompanyStatus, CompanyStatus.report_id == ReportSnapshot.id)
                .outerjoin(ZskAssessment, ZskAssessment.report_id == ReportSnapshot.id)
                .where(ReportSnapshot.id == report_id)
            )
        ).one_or_none()
        if base_row is None:
            return None
        snapshot, company, profile, status, zsk = base_row
        sections = (
            await session.execute(
                select(SectionAvailability).where(SectionAvailability.report_id == report_id)
            )
        ).scalars()
        finances = (
            await session.execute(
                select(FinancialStatement)
                .where(FinancialStatement.report_id == report_id)
                .order_by(FinancialStatement.year, FinancialStatement.ordinal)
            )
        ).scalars()
        warnings = (
            await session.execute(
                select(ImportWarning)
                .where(ImportWarning.report_id == report_id)
                .order_by(ImportWarning.created_at, ImportWarning.id)
            )
        ).scalars()
        return ReportReadData(
            report_id=snapshot.id,
            company_id=company.id,
            inn=company.inn,
            ogrn=company.ogrn,
            source_report_at=snapshot.source_report_at,
            ingested_at=snapshot.ingested_at,
            raw=snapshot.raw_jsonb,
            ingestion_status=snapshot.ingestion_status.value,
            profile=_columns(profile),
            status=_columns(status),
            zsk=_columns(zsk),
            financials=[_columns(item) for item in finances],
            sections={item.section: _columns(item) for item in sections},
            warnings=[_warning(item) for item in warnings],
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
