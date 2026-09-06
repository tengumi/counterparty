"""Company endpoints: the local index, and the composition of one check.

The rules this file exists to keep:

* a counterparty is added *pinned to one snapshot*. The ``report_id`` chosen
  when it is added is the one the project keeps reasoning about, so importing a
  newer report later never silently changes what was compared or decided on.
* a project holds one to twenty counterparties. A batch that does not fit is
  refused as a whole: applying an arbitrary first N would quietly drop the rest
  and leave the user believing they compared everything they asked for.
* one invalid row does not cancel the valid ones. Every requested item gets its
  own outcome, and a company we do not hold is reported as not found rather
  than invented.
* removing a counterparty ends its place in the current composition and nothing
  else. The row and its pinned snapshot stay, so what was already reviewed
  remains answerable.
* changing the composition changes the deal context, so it advances
  ``context_version`` under the version the caller stated. A rename does not.
"""

from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PROJECT_COMPANIES,
    AddCompaniesRequest,
    AddCompaniesResponse,
    AddCompanyItem,
    AddCompanyResult,
    CompanyAddOutcome,
    CompanyId,
    CompanySummary,
    ErrorCode,
    Page,
    ProjectCompaniesResponse,
    ProjectId,
    RemoveCompanyRequest,
    ReportId,
)
from counterparty_storage import AsyncUnitOfWork, ContextVersionConflictError
from fastapi import APIRouter, Path, Query

from ..cursors import decode_cursor, encode_cursor
from ..dependencies import ScopedProject, TenantWork
from ..errors import ApiError
from ..reads import as_page, load_company_page, load_project_details

__all__ = ["directory_router", "router"]

directory_router = APIRouter(prefix="/api/v1/companies", tags=["companies"])
router = APIRouter(prefix="/api/v1/projects/{project_id}/companies", tags=["companies"])


@directory_router.get("", response_model=Page[CompanySummary])
async def search_companies(
    uow: TenantWork,
    inn: Annotated[str | None, Query(min_length=1, max_length=12)] = None,
    query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CompanySummary]:
    """Search the companies we already hold. No external lookup is performed.

    An empty result means we hold nothing matching, which is not the same as
    the company not existing; the UI says so rather than reporting an absence
    of risk.
    """
    position = decode_cursor(cursor) if cursor is not None else None
    page = await load_company_page(
        uow,
        inn=inn,
        query=query,
        limit=limit,
        after_inn=None if position is None else position.key,
        after_id=None if position is None else position.row_id,
    )
    last = page.items[-1] if page.items else None
    next_cursor = (
        encode_cursor(last.inn, UUID(str(last.company_id)))
        if page.has_more and last is not None
        else None
    )
    return as_page(page.items, limit=limit, next_cursor=next_cursor)


@router.post("", response_model=AddCompaniesResponse)
async def add_companies(
    payload: AddCompaniesRequest, scope: ScopedProject, uow: TenantWork
) -> AddCompaniesResponse:
    """Add counterparties to a check, each pinned to one report snapshot.

    Raises:
        ApiError: If the context moved since the caller read it, or if the
            valid new rows do not fit in the remaining slots. Neither is
            applied partially.
    """
    project_id = UUID(str(scope.project_id))
    project = await uow.projects.require_writable(project_id)
    _require_context_version(project.context_version, payload.expected_context_version, project_id)

    active = await uow.project_companies.list_active(uow.scope.project(project_id))
    present = {row.company_id for row in active}
    free_slots = MAX_PROJECT_COMPANIES - len(present)

    resolved: list[tuple[AddCompanyItem, UUID | None, UUID | None]] = []
    for item in payload.items:
        company_id, report_id = await _resolve(uow, item)
        resolved.append((item, company_id, report_id))

    new_companies = {
        company_id
        for _, company_id, report_id in resolved
        if company_id is not None and report_id is not None and company_id not in present
    }
    if len(new_companies) > free_slots:
        raise ApiError(
            ErrorCode.LIMIT_EXCEEDED,
            f"a project compares at most {MAX_PROJECT_COMPANIES} counterparties",
            details={
                "limit": MAX_PROJECT_COMPANIES,
                "in_project": len(present),
                "requested_new": len(new_companies),
            },
        )

    results: list[AddCompanyResult] = []
    added_any = False
    for item, company_id, report_id in resolved:
        if company_id is None:
            results.append(
                AddCompanyResult(
                    requested=item,
                    outcome=CompanyAddOutcome.NOT_FOUND,
                    error_code=ErrorCode.NOT_FOUND,
                    message="this company is not in the local index",
                )
            )
            continue
        if report_id is None:
            results.append(
                AddCompanyResult(
                    requested=item,
                    outcome=CompanyAddOutcome.INVALID,
                    company_id=CompanyId(company_id),
                    error_code=ErrorCode.SOURCE_MISSING,
                    message="no report snapshot is held for this company",
                )
            )
            continue
        addition = await uow.project_companies.add(
            uow.scope.project(project_id), company_id=company_id, report_id=report_id
        )
        added_any = added_any or addition.created
        results.append(
            AddCompanyResult(
                requested=item,
                outcome=(
                    CompanyAddOutcome.ADDED
                    if addition.created
                    else CompanyAddOutcome.ALREADY_PRESENT
                ),
                company_id=CompanyId(addition.company.company_id),
                report_id=ReportId(addition.company.report_id),
            )
        )

    context_version = project.context_version
    if added_any:
        context_version = await uow.projects.bump_context_version(
            project_id, expected=payload.expected_context_version
        )
    await uow.commit()
    details = await load_project_details(uow, [project_id])
    return AddCompaniesResponse(
        project_id=ProjectId(project_id),
        companies=details[project_id].companies,
        context_version=context_version,
        results=results,
    )


@router.delete("/{company_id}", response_model=ProjectCompaniesResponse)
async def remove_company(
    payload: RemoveCompanyRequest,
    scope: ScopedProject,
    uow: TenantWork,
    company_id: Annotated[CompanyId, Path()],
) -> ProjectCompaniesResponse:
    """Take one counterparty out of the current composition.

    What was reviewed is not erased: the row keeps its pinned snapshot and its
    ``removed_at``, so an earlier conclusion stays explainable.

    Raises:
        ApiError: If the context moved since the caller read it, or if the
            counterparty is not part of the current composition.
    """
    project_id = UUID(str(scope.project_id))
    project = await uow.projects.require_writable(project_id)
    _require_context_version(project.context_version, payload.expected_context_version, project_id)

    await uow.project_companies.remove(
        uow.scope.project(project_id), company_id=UUID(str(company_id))
    )
    context_version = await uow.projects.bump_context_version(
        project_id, expected=payload.expected_context_version
    )
    await uow.commit()
    details = await load_project_details(uow, [project_id])
    return ProjectCompaniesResponse(
        project_id=ProjectId(project_id),
        companies=details[project_id].companies,
        context_version=context_version,
    )


async def provision_one_by_inn(
    uow: AsyncUnitOfWork, *, project_id: UUID, expected_context_version: int, inn: str
) -> dict[str, str]:
    """Pin one counterparty to a project by INN, bumping the deal context.

    Used by the internal, session-less endpoint the agent calls. Same rules as
    the batch endpoint for one row: a company we do not hold is ``not_found``,
    a company with no snapshot is ``no_report``, and adding one that is already
    in the composition is not an error. The name comes from the pinned report.
    """
    results = await uow.companies.search(inn=inn, limit=1)
    hit = next((row for row in results if row.company.inn == inn), None)
    if hit is None:
        return {"outcome": "not_found", "name": "", "inn": inn}
    name = (hit.profile.short_name if hit.profile is not None else None) or ""
    snapshot = await uow.report_snapshots.latest_for_company(hit.company.id)
    if snapshot is None:
        return {"outcome": "no_report", "name": name, "inn": inn}
    addition = await uow.project_companies.add(
        uow.scope.project(project_id), company_id=hit.company.id, report_id=snapshot.id
    )
    if addition.created:
        await uow.projects.bump_context_version(project_id, expected=expected_context_version)
    return {
        "outcome": "added" if addition.created else "already_present",
        "name": name,
        "inn": inn,
    }


async def _resolve(uow: AsyncUnitOfWork, item: AddCompanyItem) -> tuple[UUID | None, UUID | None]:
    """Resolve one requested item to a company and the snapshot to pin.

    Returns:
        The company id, or ``None`` when the local index does not hold it, and
        the snapshot to pin, or ``None`` when we hold no report for it. The two
        absences are different answers and stay different.
    """
    if item.company_id is not None:
        company = await uow.companies.get(UUID(str(item.company_id)))
    else:
        company = await uow.companies.get_by_inn(str(item.inn))
    if company is None:
        return None, None
    snapshot = await uow.report_snapshots.latest_for_company(company.id)
    return company.id, None if snapshot is None else snapshot.id


def _require_context_version(actual: int, expected: int, project_id: UUID) -> None:
    """Refuse a change written against a context the caller no longer has.

    Raises:
        ContextVersionConflictError: If the versions disagree; the caller
            re-reads instead of overwriting someone else's change.
    """
    if actual != expected:
        raise ContextVersionConflictError(project_id, expected, actual)
