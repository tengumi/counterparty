"""Read model behind the project and company responses.

The tenant-scoped repositories answer "may this caller touch this row"; this
module answers "what does one page of the answer look like" without asking the
same question once per row. Every statement here is filtered by the tenant of
the unit of work it was given, exactly as the repositories are, and every one
of them is a read: the counterparty check is written through the repositories,
and the ``reports`` schema is never written at all.

Two rules are visible in the SQL rather than left to the caller:

* a counterparty is read together with the snapshot pinned on it, not with the
  newest snapshot of that company, so a later import cannot silently change
  what a project is reasoning about;
* a company that reports no name is presented under its INN. A missing name is
  not filled in from another source, and it does not remove the company from
  the answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from counterparty_contracts import (
    CompanyId,
    CompanySummary,
    CounterpartyRole,
    ProjectCompany,
    ReportId,
)
from counterparty_storage import AsyncUnitOfWork
from counterparty_storage.reports.models import Company, CompanyProfile, ReportSnapshot
from counterparty_storage.workspace.models import Project as ProjectRow
from counterparty_storage.workspace.models import ProjectCompany as ProjectCompanyRow
from counterparty_storage.workspace.models import Thread
from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql import FromClause

__all__ = [
    "CompanyPage",
    "ProjectDetails",
    "load_company_page",
    "load_owned_projects",
    "load_project_details",
]


@dataclass(frozen=True, slots=True)
class ProjectDetails:
    """The parts of one project that are read rather than stored on its row."""

    companies: list[ProjectCompany]
    threads_count: int
    """Chats the project holds. A project always has at least the first one."""


def _display_name(short_name: str | None, full_name: str | None, inn: str) -> str:
    """Return the name to show, falling back to the INN.

    A company whose snapshot carries no name is shown by its INN rather than by
    an invented label; the identity stays exact and nothing is hidden.
    """
    for candidate in (short_name, full_name):
        if candidate is not None and candidate.strip():
            return candidate
    return inn


def _latest_snapshot() -> FromClause:
    """Select the newest snapshot id we hold per company.

    "Newest" is the source report date: importing an older file later does not
    make it the current picture.
    """
    ranked = (
        select(
            ReportSnapshot.company_id.label("company_id"),
            ReportSnapshot.id.label("report_id"),
            ReportSnapshot.source_report_at.label("source_report_at"),
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
        .alias("ranked_snapshots")
    )
    return (
        select(ranked.c.company_id, ranked.c.report_id, ranked.c.source_report_at)
        .where(ranked.c.rank == 1)
        .subquery()
        .alias("latest_snapshot")
    )


async def load_owned_projects(
    uow: AsyncUnitOfWork,
    *,
    owner_id: UUID,
    limit: int,
    updated_before: datetime | None,
    before_id: UUID | None,
) -> list[ProjectRow]:
    """Return one page of the checks this user owns, most recent activity first.

    The ownership filter is here rather than in ``ProjectRepository`` only
    because the repository does not take one yet: listing a project the caller
    cannot open would be worse than the duplication. The keyset is the pair
    ``(updated_at, id)``, so two projects touched in the same instant are still
    paged through exactly once.

    Args:
        uow: Transaction of the request; its tenant filters the statement.
        owner_id: The authenticated caller; never a value from a request body.
        limit: How many rows to read, cursor probe included.
        updated_before: Sort key of the last row of the previous page.
        before_id: Id of the last row of the previous page.

    Returns:
        The projects, deleted ones excluded.
    """
    statement = (
        select(ProjectRow)
        .where(
            ProjectRow.tenant_id == uow.scope.tenant_id,
            ProjectRow.owner_id == owner_id,
            ProjectRow.deleted_at.is_(None),
        )
        .order_by(ProjectRow.updated_at.desc(), ProjectRow.id.desc())
    )
    if updated_before is not None:
        keyset = ProjectRow.updated_at < updated_before
        if before_id is not None:
            keyset = keyset | and_(
                ProjectRow.updated_at == updated_before, ProjectRow.id < before_id
            )
        statement = statement.where(keyset)
    return list((await uow.session.execute(statement.limit(limit))).scalars())


async def load_project_details(
    uow: AsyncUnitOfWork, project_ids: Sequence[UUID]
) -> dict[UUID, ProjectDetails]:
    """Return the composition and chat count of each requested project.

    Two statements answer a whole page, so the size of the page does not
    decide how many queries a list costs.

    Args:
        uow: Transaction of the request; its tenant filters every statement.
        project_ids: Projects of that tenant to describe.

    Returns:
        One entry per requested project, present even when the project holds
        no counterparties.
    """
    details: dict[UUID, ProjectDetails] = {
        project_id: ProjectDetails(companies=[], threads_count=0) for project_id in project_ids
    }
    if not project_ids:
        return details

    tenant_id = uow.scope.tenant_id
    ids = list(project_ids)
    companies_by_project: dict[UUID, list[ProjectCompany]] = {project_id: [] for project_id in ids}

    composition = (
        select(
            ProjectCompanyRow.project_id,
            ProjectCompanyRow.company_id,
            ProjectCompanyRow.report_id,
            ProjectCompanyRow.role,
            ProjectCompanyRow.shortlisted,
            ProjectCompanyRow.added_at,
            Company.inn,
            CompanyProfile.short_name,
            CompanyProfile.full_name,
        )
        .join(Company, Company.id == ProjectCompanyRow.company_id)
        .outerjoin(CompanyProfile, CompanyProfile.report_id == ProjectCompanyRow.report_id)
        .where(
            ProjectCompanyRow.tenant_id == tenant_id,
            ProjectCompanyRow.project_id.in_(ids),
            ProjectCompanyRow.removed_at.is_(None),
        )
        .order_by(ProjectCompanyRow.project_id, ProjectCompanyRow.slot)
    )
    for row in (await uow.session.execute(composition)).all():
        companies_by_project[row.project_id].append(
            ProjectCompany(
                company_id=CompanyId(row.company_id),
                report_id=ReportId(row.report_id),
                inn=row.inn,
                short_name=_display_name(row.short_name, row.full_name, row.inn),
                role=CounterpartyRole(row.role.value),
                shortlisted=row.shortlisted,
                added_at=row.added_at,
            )
        )

    threads = (
        select(Thread.project_id, func.count(Thread.id))
        .where(Thread.tenant_id == tenant_id, Thread.project_id.in_(ids))
        .group_by(Thread.project_id)
    )
    counts = {row[0]: row[1] for row in (await uow.session.execute(threads)).all()}

    return {
        project_id: ProjectDetails(
            companies=companies_by_project[project_id],
            threads_count=counts.get(project_id, 0),
        )
        for project_id in ids
    }


@dataclass(frozen=True, slots=True)
class CompanyPage:
    """One page of the local company index."""

    items: list[CompanySummary]
    has_more: bool


async def load_company_page(
    uow: AsyncUnitOfWork,
    *,
    inn: str | None,
    query: str | None,
    limit: int,
    after_inn: str | None,
    after_id: UUID | None,
) -> CompanyPage:
    """Search the companies we already hold. No external lookup is performed.

    A company is returned whether or not we hold a snapshot for it; the absence
    of a snapshot is reported as an absent ``latest_report_id`` rather than by
    dropping the company from the answer.

    Args:
        uow: Transaction of the request.
        inn: Exact INN to look up.
        query: Substring of the INN or of a reported name.
        limit: Page size.
        after_inn: Keyset cursor: INN of the last item of the previous page.
        after_id: Keyset cursor: id of the last item of the previous page.

    Returns:
        The page and whether the index holds more matches after it.
    """
    latest = _latest_snapshot()
    statement = (
        select(
            Company.id,
            Company.inn,
            Company.ogrn,
            latest.c.report_id,
            latest.c.source_report_at,
            CompanyProfile.short_name,
            CompanyProfile.full_name,
        )
        .outerjoin(latest, latest.c.company_id == Company.id)
        .outerjoin(CompanyProfile, CompanyProfile.report_id == latest.c.report_id)
        .order_by(Company.inn, Company.id)
    )
    if inn is not None:
        statement = statement.where(Company.inn == inn)
    if query is not None:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Company.inn.ilike(pattern),
                CompanyProfile.short_name.ilike(pattern),
                CompanyProfile.full_name.ilike(pattern),
            )
        )
    if after_inn is not None and after_id is not None:
        statement = statement.where(
            or_(
                Company.inn > after_inn,
                and_(Company.inn == after_inn, Company.id > after_id),
            )
        )

    rows = (await uow.session.execute(statement.limit(limit + 1))).all()
    has_more = len(rows) > limit
    return CompanyPage(
        items=[
            CompanySummary(
                company_id=CompanyId(row.id),
                inn=row.inn,
                ogrn=row.ogrn,
                short_name=_display_name(row.short_name, row.full_name, row.inn),
                full_name=row.full_name,
                latest_report_id=None if row.report_id is None else ReportId(row.report_id),
                latest_report_at=row.source_report_at,
            )
            for row in rows[:limit]
        ],
        has_more=has_more,
    )
