"""Read model behind the project and company responses.

Repositories read the company index and tenant-scoped project compositions in
batches; this module maps those records to the public DTOs and counts chats
for the whole project page. The ``reports`` schema is never written at all.

Two rules remain explicit in the response:

* a counterparty is read together with the snapshot pinned on it, not with the
  newest snapshot of that company, so a later import cannot silently change
  what a project is reasoning about;
* a company that reports no name is presented under its INN. A missing name is
  not filled in from another source, and it does not remove the company from
  the answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from counterparty_contracts import (
    CompanyId,
    CompanySummary,
    CounterpartyRole,
    ProjectCompany,
    ReportId,
)
from counterparty_storage import AsyncUnitOfWork
from counterparty_storage.workspace.models import Thread
from sqlalchemy import func, select

__all__ = [
    "CompanyPage",
    "ProjectDetails",
    "load_company_page",
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

    compositions = await uow.project_companies.list_active_for_projects(ids)
    for project_id, records in compositions.items():
        for record in records:
            membership, company, profile = record.membership, record.company, record.profile
            companies_by_project[project_id].append(
                ProjectCompany(
                    company_id=CompanyId(membership.company_id),
                    report_id=ReportId(membership.report_id),
                    inn=company.inn,
                    short_name=_display_name(
                        None if profile is None else profile.short_name,
                        None if profile is None else profile.full_name,
                        company.inn,
                    ),
                    role=CounterpartyRole(membership.role.value),
                    shortlisted=membership.shortlisted,
                    added_at=membership.added_at,
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
        query: Literal substring of INN, OGRN or the latest reported name.
        limit: Page size.
        after_inn: Keyset cursor: INN of the last item of the previous page.
        after_id: Keyset cursor: id of the last item of the previous page.

    Returns:
        The page and whether the index holds more matches after it.
    """
    rows = await uow.companies.search(
        inn=inn,
        query=query,
        limit=limit + 1,
        after_inn=after_inn,
        after_id=after_id,
    )
    return CompanyPage(
        items=[
            CompanySummary(
                company_id=CompanyId(row.company.id),
                inn=row.company.inn,
                ogrn=row.company.ogrn,
                short_name=_display_name(
                    None if row.profile is None else row.profile.short_name,
                    None if row.profile is None else row.profile.full_name,
                    row.company.inn,
                ),
                full_name=None if row.profile is None else row.profile.full_name,
                latest_report_id=None if row.report is None else ReportId(row.report.id),
                latest_report_at=None if row.report is None else row.report.source_report_at,
            )
            for row in rows[:limit]
        ],
        has_more=len(rows) > limit,
    )
