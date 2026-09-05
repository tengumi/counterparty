"""Operational health endpoint."""

from typing import Literal

from counterparty_contracts import __version__ as contracts_version
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    """Typed service readiness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"]
    service: Literal["ui_api"] = "ui_api"
    contracts_version: str


@router.get(
    "/healthz",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(request: Request) -> HealthResponse | JSONResponse:
    """Report whether the application lifespan has started successfully."""
    response = HealthResponse(
        status="ok" if getattr(request.app.state, "ready", False) else "unavailable",
        contracts_version=contracts_version,
    )
    if response.status == "unavailable":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response
