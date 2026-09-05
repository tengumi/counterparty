"""Read-only repositories over the ``reports`` schema.

The provided report is immutable. These classes expose no way to write it, so a
service that holds one still cannot change what a snapshot says — which is the
same rule the ``mcp`` and ``ui_api`` database roles enforce one layer down.

They are not tenant-scoped: the report corpus is shared, and which snapshot a
project is allowed to reason about is decided by ``workspace``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..reports.models import Company, ReportSnapshot

__all__ = ["CompanyReadRepository", "ReportSnapshotReadRepository"]


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
            .order_by(ReportSnapshot.source_report_at.desc(), ReportSnapshot.ingested_at.desc())
            .limit(1)
        )
        return (await self._session.execute(statement)).scalars().first()
