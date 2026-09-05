"""Read typed sections and authorized project report evidence."""

from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    ErrorCode,
    GetReportSectionInput,
    PartyRole,
    ReportEvidence,
    ReportId,
    ReportSection,
    ReportSectionFilters,
    ReportSectionName,
)
from counterparty_domain.report_evidence import build_report_evidence
from counterparty_domain.report_reads import resolve_report_evidence_id
from counterparty_domain.report_sections import build_report_section
from counterparty_storage.workspace.models import ProjectCompany
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from .dependencies import ScopedProject, TenantWork
from .errors import ApiError
from .report_loader import load_report_data

router = APIRouter(prefix="/api/v1", tags=["reports"])


class SectionQuery(BaseModel):
    """Flat REST query equivalent of the shared MCP section input."""

    model_config = ConfigDict(extra="forbid")
    years: list[int] | None = None
    active: bool | None = None
    role: PartyRole | None = None
    status_raw: str | None = Field(default=None, min_length=1)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    limit: int = Field(default=20, ge=1, le=100)


@router.get("/reports/{report_id}/sections/{section}", response_model=ReportSection)
async def get_report_section(
    uow: TenantWork,
    report_id: Annotated[UUID, Path()],
    section: Annotated[ReportSectionName, Path()],
    query: Annotated[SectionQuery, Query()],
) -> ReportSection:
    """Read one page of the shared corpus, requiring an authenticated session."""
    try:
        filters = ReportSectionFilters.model_validate(query.model_dump(exclude={"limit", "cursor"}))
        request = GetReportSectionInput(
            report_id=ReportId(report_id),
            section=section,
            filters=filters,
            limit=query.limit,
            cursor=query.cursor,
        )
    except ValidationError as error:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "the section filters are not valid") from error
    loaded = await load_report_data(uow, [report_id])
    if not loaded:
        raise ApiError(ErrorCode.NOT_FOUND, "report not found")
    try:
        return build_report_section(loaded[0], request)
    except ValueError as error:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "the section cursor is not valid") from error


@router.get("/projects/{project_id}/evidence/{ref_id:path}", response_model=ReportEvidence)
async def get_project_evidence(
    scope: ScopedProject,
    uow: TenantWork,
    ref_id: Annotated[str, Path(min_length=1, max_length=2048)],
) -> ReportEvidence:
    """Resolve only issued refs from a snapshot ever pinned in this project."""
    locator = resolve_report_evidence_id(ref_id)
    if locator is None:
        raise ApiError(ErrorCode.NOT_FOUND, "evidence not found")
    report_id, _ = locator
    # Historical membership is intentional: removing a company does not erase
    # the sources used by an older artifact or decision in the same project.
    permitted = await uow.session.scalar(
        select(ProjectCompany.id)
        .where(
            ProjectCompany.tenant_id == UUID(str(scope.tenant_id)),
            ProjectCompany.project_id == UUID(str(scope.project_id)),
            ProjectCompany.report_id == report_id,
        )
        .limit(1)
    )
    if permitted is None:
        raise ApiError(ErrorCode.NOT_FOUND, "evidence not found")
    loaded = await load_report_data(uow, [report_id])
    if not loaded:
        raise ApiError(ErrorCode.NOT_FOUND, "evidence not found")
    try:
        resolved = build_report_evidence(loaded[0], ref_id)
    except ValueError as error:
        raise ApiError(
            ErrorCode.LIMIT_EXCEEDED, "source fragment is too large; open an individual field"
        ) from error
    if resolved is None:
        raise ApiError(ErrorCode.NOT_FOUND, "evidence not found")
    return resolved
