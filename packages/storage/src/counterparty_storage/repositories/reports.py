"""Read-only repositories over the ``reports`` schema.

The provided report is immutable. These classes expose no way to write it, so a
service that holds one still cannot change what a snapshot says — which is the
same rule the ``mcp`` and ``ui_api`` database roles enforce one layer down.

They are not tenant-scoped: the report corpus is shared, and which snapshot a
project is allowed to reason about is decided by ``workspace``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import FromClause

from ..reports.models import (
    Company,
    CompanyProfile,
    CompanyStatus,
    FinancialStatement,
    ImportWarning,
    ReportSnapshot,
    SectionAvailability,
    ZskAssessment,
)

__all__ = [
    "CompanyReadRepository",
    "CompanySearchResult",
    "ReportReadBundle",
    "ReportSnapshotReadRepository",
]


@dataclass(frozen=True, slots=True)
class CompanySearchResult:
    """One local company match and its newest available report identity."""

    company: Company
    report: ReportSnapshot | None
    profile: CompanyProfile | None


@dataclass(frozen=True, slots=True)
class ReportReadBundle:
    """Loaded rows of one pinned snapshot, with no derived DTOs or service policy.

    All attributes are loaded eagerly. Child records retain stable source order
    so either read service can produce the same deterministic projection.
    """

    snapshot: ReportSnapshot
    company: Company
    profile: CompanyProfile | None
    status: CompanyStatus | None
    zsk: ZskAssessment | None
    financials: tuple[FinancialStatement, ...]
    sections: tuple[SectionAvailability, ...]
    warnings: tuple[ImportWarning, ...]


def _latest_snapshot() -> FromClause:
    """Return a relation containing the newest snapshot id per company."""
    ranked = (
        select(
            ReportSnapshot.id.label("report_id"),
            ReportSnapshot.company_id.label("company_id"),
            func.row_number()
            .over(
                partition_by=ReportSnapshot.company_id,
                order_by=(
                    ReportSnapshot.source_report_at.desc(),
                    ReportSnapshot.ingested_at.desc(),
                    ReportSnapshot.id.desc(),
                ),
            )
            .label("rank"),
        )
        .subquery()
        .alias("ranked_company_snapshots")
    )
    return (
        select(ranked.c.report_id, ranked.c.company_id)
        .where(ranked.c.rank == 1)
        .subquery()
        .alias("latest_company_snapshot")
    )


class CompanyReadRepository:
    """Look up a company of the shared corpus."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one session. It opens nothing itself."""
        self._session = session

    async def get(self, company_id: UUID) -> Company | None:
        """Return the company, or ``None`` when the corpus does not hold it."""
        return await self._session.get(Company, company_id)

    async def get_by_inn(self, inn: str) -> Company | None:
        """Return the company with this INN.

        The INN is matched as the string it is stored as. A value that is not
        held is simply absent; nothing is invented for it.
        """
        statement = select(Company).where(Company.inn == inn)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def search(
        self,
        *,
        limit: int,
        inn: str | None = None,
        query: str | None = None,
        after_inn: str | None = None,
        after_id: UUID | None = None,
    ) -> list[CompanySearchResult]:
        """Search only the locally stored index in stable keyset order.

        ``inn`` is exact; ``query`` is a case-insensitive literal substring of
        INN, OGRN, or a name from the newest report. The repository deliberately
        performs no external lookup. Callers may request ``limit + 1`` rows to
        derive a ``has_more`` flag without a count query.
        """
        latest = _latest_snapshot()
        statement = (
            select(Company, ReportSnapshot, CompanyProfile)
            .outerjoin(latest, latest.c.company_id == Company.id)
            .outerjoin(ReportSnapshot, ReportSnapshot.id == latest.c.report_id)
            .outerjoin(CompanyProfile, CompanyProfile.report_id == latest.c.report_id)
            .order_by(Company.inn, Company.id)
        )
        if inn is not None:
            statement = statement.where(Company.inn == inn)
        if query is not None:
            statement = statement.where(
                or_(
                    Company.inn.icontains(query, autoescape=True),
                    Company.ogrn.icontains(query, autoescape=True),
                    CompanyProfile.short_name.icontains(query, autoescape=True),
                    CompanyProfile.full_name.icontains(query, autoescape=True),
                )
            )
        if after_inn is not None and after_id is not None:
            statement = statement.where(
                or_(
                    Company.inn > after_inn,
                    and_(Company.inn == after_inn, Company.id > after_id),
                )
            )
        rows = (await self._session.execute(statement.limit(limit))).all()
        return [
            CompanySearchResult(company=company, report=report, profile=profile)
            for company, report, profile in rows
        ]


class ReportSnapshotReadRepository:
    """Look up the provided report snapshots of a company."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one session. It opens nothing itself."""
        self._session = session

    async def get(self, report_id: UUID) -> ReportSnapshot | None:
        """Return one snapshot by its id."""
        return await self._session.get(ReportSnapshot, report_id)

    async def latest_for_company(self, company_id: UUID) -> ReportSnapshot | None:
        """Return the newest snapshot we hold for the company.

        "Newest" is the source report date, not the ingestion time: importing
        an older file later does not make it the current picture.
        """
        statement = (
            select(ReportSnapshot)
            .where(ReportSnapshot.company_id == company_id)
            .order_by(
                ReportSnapshot.source_report_at.desc(),
                ReportSnapshot.ingested_at.desc(),
                ReportSnapshot.id.desc(),
            )
            .limit(1)
        )
        return (await self._session.execute(statement)).scalars().first()

    async def get_read_bundles(self, report_ids: Sequence[UUID]) -> list[ReportReadBundle]:
        """Read exact snapshots and their normalized children in four statements.

        Requested order is preserved after removing duplicate ids. Unknown ids
        are omitted, and missing child data stays empty rather than synthesized.
        An empty request performs no I/O. No report is replaced with its latest
        version and this method never writes or commits.
        """
        ids = list(dict.fromkeys(report_ids))
        if not ids:
            return []
        base_rows = (
            await self._session.execute(
                select(ReportSnapshot, Company, CompanyProfile, CompanyStatus, ZskAssessment)
                .join(Company, Company.id == ReportSnapshot.company_id)
                .outerjoin(CompanyProfile, CompanyProfile.report_id == ReportSnapshot.id)
                .outerjoin(CompanyStatus, CompanyStatus.report_id == ReportSnapshot.id)
                .outerjoin(ZskAssessment, ZskAssessment.report_id == ReportSnapshot.id)
                .where(ReportSnapshot.id.in_(ids))
            )
        ).all()
        sections_by_report: dict[UUID, dict[str, SectionAvailability]] = {item: {} for item in ids}
        for section_entry in (
            await self._session.execute(
                select(SectionAvailability)
                .where(SectionAvailability.report_id.in_(ids))
                .order_by(SectionAvailability.report_id, SectionAvailability.section)
            )
        ).scalars():
            sections_by_report[section_entry.report_id][section_entry.section] = section_entry
        finances_by_report: dict[UUID, list[FinancialStatement]] = {item: [] for item in ids}
        for financial_entry in (
            await self._session.execute(
                select(FinancialStatement)
                .where(FinancialStatement.report_id.in_(ids))
                .order_by(
                    FinancialStatement.report_id,
                    FinancialStatement.year,
                    FinancialStatement.ordinal,
                )
            )
        ).scalars():
            finances_by_report[financial_entry.report_id].append(financial_entry)
        warnings_by_report: dict[UUID, list[ImportWarning]] = {item: [] for item in ids}
        for warning_entry in (
            await self._session.execute(
                select(ImportWarning)
                .where(ImportWarning.report_id.in_(ids))
                .order_by(ImportWarning.report_id, ImportWarning.created_at, ImportWarning.id)
            )
        ).scalars():
            if warning_entry.report_id is not None:
                warnings_by_report[warning_entry.report_id].append(warning_entry)

        by_id = {
            snapshot.id: ReportReadBundle(
                snapshot=snapshot,
                company=company,
                profile=profile,
                status=status,
                zsk=zsk,
                financials=tuple(finances_by_report[snapshot.id]),
                sections=tuple(sections_by_report[snapshot.id].values()),
                warnings=tuple(warnings_by_report[snapshot.id]),
            )
            for snapshot, company, profile, status, zsk in base_rows
        }
        return [by_id[report_id] for report_id in ids if report_id in by_id]
