"""The user's own decision and the AI conclusions it may be weighed against.

Two rules of Specs 09 §5 / 10 §5 shape this file:

* a decision is the person's, not the model's. The author is taken from the
  authenticated session and never from the body, a decision may be recorded
  with no artifact at all, and disagreeing with one is a valid outcome.
* an artifact version is immutable. ``latest`` collapses to the newest version
  of each artifact, which is what the UI shows by default; the older versions
  stay readable because a decision may still point at one.

Nothing here writes an artifact: the agent creates those once it can reason for
a project. Until then ``GET /artifacts`` is an honest empty list.
"""

from typing import Annotated
from uuid import UUID

from counterparty_contracts import (
    AnalysisArtifact,
    CreateDecisionRequest,
    ErrorCode,
    UserDecision,
)
from counterparty_storage.workspace.enums import DecisionOutcome as StorageDecisionOutcome
from fastapi import APIRouter, Query, status

from .dependencies import CurrentSession, ScopedProject, TenantWork
from .errors import ApiError
from .views import as_analysis_artifact, as_user_decision

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/projects", tags=["decisions"])


@router.get("/{project_id}/decisions", response_model=list[UserDecision])
async def list_decisions(scope: ScopedProject, uow: TenantWork) -> list[UserDecision]:
    """Return the project's recorded decisions, newest first."""
    project_scope = uow.scope.project(UUID(str(scope.project_id)))
    rows = await uow.decisions.list_for_project(project_scope)
    return [as_user_decision(row) for row in rows]


@router.post(
    "/{project_id}/decisions",
    response_model=UserDecision,
    status_code=status.HTTP_201_CREATED,
)
async def record_decision(
    payload: CreateDecisionRequest,
    scope: ScopedProject,
    session: CurrentSession,
    uow: TenantWork,
) -> UserDecision:
    """Record one decision under the caller's own name.

    The request body is held to the same invariants as the stored decision
    (a conditional outcome names its condition, an artifact reference pins the
    version it read); FastAPI rejects a body that breaks them before this runs.

    Raises:
        ApiError: If the decision cites an artifact version this project does
            not hold, or if the project no longer accepts writes.
    """
    project_scope = uow.scope.project(UUID(str(scope.project_id)))
    based_on_artifact_id = (
        None if payload.based_on_artifact_id is None else UUID(str(payload.based_on_artifact_id))
    )
    if based_on_artifact_id is not None:
        cited = await uow.artifacts.get_version(
            project_scope,
            artifact_id=based_on_artifact_id,
            version=payload.based_on_artifact_version or 0,
        )
        if cited is None:
            raise ApiError(ErrorCode.NOT_FOUND, "the cited artifact version was not found")

    supersedes_id = None if payload.supersedes_id is None else UUID(str(payload.supersedes_id))
    if supersedes_id is not None:
        superseded = await uow.decisions.get(project_scope, supersedes_id)
        if superseded is None:
            raise ApiError(ErrorCode.NOT_FOUND, "the superseded decision was not found")

    row = await uow.decisions.record(
        project_scope,
        author_user_id=UUID(str(session.user_id)),
        outcome=StorageDecisionOutcome(payload.outcome.value),
        rationale=payload.rationale,
        conditions=list(payload.conditions),
        company_ids=[UUID(str(company_id)) for company_id in payload.company_ids],
        context_version=payload.context_version,
        evidence_refs=[str(ref) for ref in payload.evidence_refs],
        based_on_artifact_id=based_on_artifact_id,
        based_on_artifact_version=payload.based_on_artifact_version,
        supersedes_id=supersedes_id,
    )
    await uow.commit()
    return as_user_decision(row)


@router.get("/{project_id}/artifacts", response_model=list[AnalysisArtifact])
async def list_artifacts(
    scope: ScopedProject,
    uow: TenantWork,
    latest: Annotated[bool, Query()] = False,
) -> list[AnalysisArtifact]:
    """Return the project's AI conclusions, newest first.

    With ``latest=true`` only the newest version of each artifact is returned.
    """
    project_scope = uow.scope.project(UUID(str(scope.project_id)))
    rows = await uow.artifacts.list_for_project(project_scope, latest_only=latest)
    return [as_analysis_artifact(row) for row in rows]
