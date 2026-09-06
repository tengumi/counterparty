"""Session-less internal endpoints, authorized by a shared token.

The agent service has no browser session, so it cannot use the ownership
dependencies the rest of the API is built on. It still must not write
``workspace`` directly — that privilege is the UI backend's. This router is the
narrow seam between the two: one endpoint, one shared secret, and the tenant is
read from the project row rather than trusted from the caller.
"""

import secrets
from typing import Annotated
from uuid import UUID

from counterparty_contracts import ErrorCode
from counterparty_storage import TenantScope, unit_of_work
from counterparty_storage.workspace.models import Project
from fastapi import APIRouter, Depends, Header, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import Settings
from ..database import SessionFactory
from ..dependencies import get_session_factory, get_settings
from ..errors import ApiError
from .companies import provision_one_by_inn

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


class InternalAddCompanyRequest(BaseModel):
    """One counterparty to pin, named by INN."""

    inn: str = Field(pattern=r"^\d{10}(?:\d{2})?$")


class InternalAddCompanyResponse(BaseModel):
    """The outcome of one internal add-company call."""

    outcome: str
    """``added`` | ``already_present`` | ``not_found`` | ``no_report``."""
    name: str
    inn: str


def _authorize(settings: Settings, token: str | None) -> None:
    expected = settings.internal_token
    if (
        expected is None
        or token is None
        or not secrets.compare_digest(token, expected.get_secret_value())
    ):
        raise ApiError(ErrorCode.UNAUTHORIZED, "a valid internal token is required")


@router.post("/projects/{project_id}/companies", response_model=InternalAddCompanyResponse)
async def internal_add_company(
    payload: InternalAddCompanyRequest,
    project_id: Annotated[UUID, Path()],
    settings: Annotated[Settings, Depends(get_settings)],
    factory: Annotated[SessionFactory | None, Depends(get_session_factory)],
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> InternalAddCompanyResponse:
    """Pin a counterparty to a project on the agent's behalf.

    Raises:
        ApiError: If the token is wrong, storage is unavailable, or the project
            does not exist.
    """
    _authorize(settings, x_internal_token)
    if factory is None:
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "the workspace storage is not available",
            retryable=True,
        )
    async with factory() as probe:
        row = (
            await probe.execute(
                select(Project.tenant_id, Project.owner_id).where(
                    Project.id == project_id, Project.deleted_at.is_(None)
                )
            )
        ).first()
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "project not found")

    scope = TenantScope(tenant_id=row.tenant_id, actor_user_id=row.owner_id)
    async with unit_of_work(factory, scope) as uow:
        project = await uow.projects.require_writable(project_id)
        outcome = await provision_one_by_inn(
            uow,
            project_id=project_id,
            expected_context_version=project.context_version,
            inn=payload.inn,
        )
        await uow.commit()
    return InternalAddCompanyResponse(**outcome)
