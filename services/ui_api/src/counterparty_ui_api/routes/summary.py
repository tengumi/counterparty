"""The report-screen "на что обратить внимание" block.

The UI backend holds the report data and the user's task (the project title);
the agent service holds the model. This route is the thin call-through: resolve
and authorise the snapshot, ask the agent once, cache the answer against the
project's context version so opening the report again is instant.
"""

from typing import Annotated, Literal
from uuid import UUID

import httpx
from counterparty_contracts import ErrorCode
from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from ..config import Settings
from ..dependencies import ScopedProject, TenantWork, get_settings
from ..errors import ApiError

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/projects", tags=["reports"])


class SummaryBullet(BaseModel):
    """One line of the orientation block."""

    tone: Literal["risk", "ok", "neutral"] = "neutral"
    text: str


class ReportSummary(BaseModel):
    """The orientation block shown above the raw report sections."""

    bullets: list[SummaryBullet] = Field(default_factory=list)
    caveat: str = ""


_cache: dict[str, ReportSummary] = {}


@router.get(
    "/{project_id}/reports/{report_id}/summary",
    response_model=ReportSummary,
)
async def get_report_summary(
    scope: ScopedProject,
    uow: TenantWork,
    settings: Annotated[Settings, Depends(get_settings)],
    report_id: Annotated[UUID, Path()],
) -> ReportSummary:
    """Build (or replay) the general orientation block for one pinned report."""
    if settings.agent_url is None:
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, "summary is not configured", retryable=True
        )
    project_id = UUID(str(scope.project_id))
    active = await uow.project_companies.list_active(uow.scope.project(project_id))
    if report_id not in {row.report_id for row in active}:
        raise ApiError(ErrorCode.NOT_FOUND, "report is not pinned in this project")

    # The pinned snapshot is immutable, so the block depends only on the report.
    cached = _cache.get(str(report_id))
    if cached is not None:
        return cached

    headers = {}
    if settings.internal_token is not None:
        headers["X-Internal-Token"] = settings.internal_token.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{settings.agent_url.rstrip('/')}/api/v1/internal/summary",
                json={"report_id": str(report_id)},
                headers=headers,
            )
    except httpx.HTTPError as error:
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, "the assistant is unavailable", retryable=True
        ) from error
    if response.status_code != 200:
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "the assistant could not build a summary",
            retryable=True,
        )
    summary = ReportSummary.model_validate(response.json())
    _cache[str(report_id)] = summary
    return summary
