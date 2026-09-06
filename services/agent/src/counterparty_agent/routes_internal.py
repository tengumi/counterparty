"""Session-less internal endpoints the UI backend calls, token-authorized.

The UI backend has the report data and the user's task but no model; the agent
has the model and the report tools. This is the one seam for the report-screen
orientation block: same shared secret as the reverse direction.
"""

import secrets

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from .config import AgentSettings
from .summary import ReportSummary, build_report_summary

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


class SummaryRequest(BaseModel):
    """Which report to summarise."""

    report_id: str


def _authorize(settings: AgentSettings, token: str | None) -> None:
    expected = settings.ui_api_internal_token
    if (
        expected is None
        or token is None
        or not secrets.compare_digest(token, expected.get_secret_value())
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad internal token")


@router.post("/summary", response_model=ReportSummary)
async def summary(
    payload: SummaryRequest,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> ReportSummary:
    """Build the "на что обратить внимание" block for one report."""
    settings = AgentSettings()
    _authorize(settings, x_internal_token)
    try:
        return await build_report_summary(settings, report_id=payload.report_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
