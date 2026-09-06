"""Pinned report overview and deterministic project comparison endpoints."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    CompanyOverview,
    CompareCompaniesInput,
    ErrorCode,
    ProjectComparison,
)
from counterparty_domain import COMPARISON_RULE_VERSION, build_comparison_rows
from counterparty_domain.report_reads import (
    build_company_overview,
    report_evidence_id,
    resolve_report_evidence_id,
)
from fastapi import APIRouter, Path

from ..dependencies import ScopedProject, TenantWork
from ..errors import ApiError
from ..loaders.reports import load_report_data

__all__ = ["report_evidence_id", "resolve_report_evidence_id", "router"]
router = APIRouter(prefix="/api/v1", tags=["reports"])


async def _load_overviews(
    uow: TenantWork, report_ids: Sequence[UUID], *, include_invalid: bool = False
) -> list[CompanyOverview]:
    """Load the shared deterministic overview of the exact requested snapshots."""
    return [
        build_company_overview(data)
        for data in await load_report_data(uow, report_ids)
        if include_invalid or data.ingestion_status != "invalid"
    ]


@router.get("/reports/{report_id}/overview", response_model=CompanyOverview)
async def get_company_overview(
    uow: TenantWork,
    report_id: Annotated[UUID, Path()],
) -> CompanyOverview:
    """Return the typed summary of exactly the requested snapshot."""
    loaded = await _load_overviews(uow, [report_id])
    if not loaded:
        raise ApiError(ErrorCode.NOT_FOUND, "report not found")
    return loaded[0]


@router.post("/projects/{project_id}/comparisons", response_model=ProjectComparison)
async def compare_project_companies(
    payload: CompareCompaniesInput,
    scope: ScopedProject,
    uow: TenantWork,
) -> ProjectComparison:
    """Compare only snapshots pinned in the authenticated project."""
    project_id = UUID(str(scope.project_id))
    active = await uow.project_companies.list_active(uow.scope.project(project_id))
    permitted = {row.report_id for row in active}
    requested = [UUID(str(report_id)) for report_id in payload.report_ids]
    if any(report_id not in permitted for report_id in requested):
        raise ApiError(ErrorCode.NOT_FOUND, "report not found in project")
    overviews = await _load_overviews(uow, requested, include_invalid=True)
    rows, warnings = build_comparison_rows(
        payload.report_ids,
        overviews,
        payload.criteria,
        year_policy=payload.year_policy,
        year=payload.year,
    )
    return ProjectComparison(
        project_id=scope.project_id,
        report_ids=payload.report_ids,
        criteria=payload.criteria,
        year_policy=payload.year_policy,
        year=payload.year,
        rows=rows,
        warnings=warnings,
        rule_version=COMPARISON_RULE_VERSION,
    )
