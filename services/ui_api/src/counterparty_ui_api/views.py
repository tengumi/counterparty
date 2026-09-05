"""Turning stored rows into the public DTOs of the REST contract.

The DTOs are the contract; this module is the only place that decides how a
row becomes one, so two endpoints cannot disagree about what a project looks
like. Nothing is invented here: a field the workspace does not hold yet is
absent rather than defaulted to something reassuring.
"""

from uuid import UUID

from counterparty_contracts import (
    AnalysisArtifact,
    ArtifactFreshness,
    ArtifactGround,
    ArtifactId,
    CompanyId,
    DecisionId,
    DecisionOutcome,
    EvidenceRefId,
    Page,
    PageInfo,
    Project,
    ProjectId,
    ReportId,
    RunId,
    RunInfo,
    RunStatus,
    SaveStatus,
    ThreadConversationState,
    ThreadId,
    UserDecision,
    UserId,
    WorkflowStatus,
)
from counterparty_storage.workspace.enums import AgentRunStatus
from counterparty_storage.workspace.models import AgentRun as AgentRunRow
from counterparty_storage.workspace.models import AnalysisArtifact as AnalysisArtifactRow
from counterparty_storage.workspace.models import Project as ProjectRow
from counterparty_storage.workspace.models import UserDecision as UserDecisionRow

from .reads import ProjectDetails

__all__ = [
    "as_analysis_artifact",
    "as_page",
    "as_project",
    "as_thread_conversation",
    "as_user_decision",
]

_ACTIVE_RUN_STATUSES = frozenset(
    {AgentRunStatus.ACCEPTED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING}
)
"""Run states the UI can still reconnect to; matches the ``uq_agent_runs_active_thread``
partial index in storage."""


def as_project(row: ProjectRow, details: ProjectDetails) -> Project:
    """Render one stored project as the public DTO.

    ``last_open_question``, ``latest_artifact`` and ``latest_decision`` stay
    absent here on purpose: the conversation projection is the agent service's,
    and decisions and artifacts have their own endpoints. Folding a summary of
    them into every project row would be a second, drifting copy, so a client
    that needs them asks for them.

    Raises:
        ValueError: If the project has no default chat. Every project is
            created with its first one, so this is a broken row rather than a
            state a caller can reach.
    """
    if row.default_thread_id is None:
        raise ValueError(f"project {row.id} has no default thread")
    return Project(
        id=ProjectId(row.id),
        title=row.title,
        default_thread_id=ThreadId(row.default_thread_id),
        threads_count=details.threads_count,
        context_version=row.context_version,
        workflow_status=WorkflowStatus(row.workflow_status.value),
        created_at=row.created_at,
        updated_at=row.updated_at,
        companies=details.companies,
    )


def as_user_decision(row: UserDecisionRow) -> UserDecision:
    """Render one recorded decision as the public DTO.

    The identifier lists were stored as JSON strings; they are read back into
    the typed fields without reinterpreting them.
    """
    return UserDecision(
        id=DecisionId(row.id),
        project_id=ProjectId(row.project_id),
        outcome=DecisionOutcome(row.outcome.value),
        company_ids=[CompanyId(UUID(value)) for value in row.company_ids],
        rationale=row.rationale,
        conditions=list(row.conditions),
        based_on_artifact_id=(
            None if row.based_on_artifact_id is None else ArtifactId(row.based_on_artifact_id)
        ),
        based_on_artifact_version=row.based_on_artifact_version,
        context_version=row.context_version,
        evidence_refs=[EvidenceRefId(value) for value in row.evidence_refs],
        author_user_id=UserId(row.author_user_id),
        created_at=row.created_at,
        supersedes_id=(None if row.supersedes_id is None else DecisionId(row.supersedes_id)),
    )


def as_analysis_artifact(row: AnalysisArtifactRow) -> AnalysisArtifact:
    """Render one immutable artifact version as the public DTO."""
    return AnalysisArtifact(
        id=ArtifactId(row.id),
        version=row.version,
        project_id=ProjectId(row.project_id),
        based_on_context_version=row.based_on_context_version,
        report_ids=[ReportId(UUID(value)) for value in row.report_ids],
        question=row.question,
        summary=row.summary,
        grounds=[
            ArtifactGround(
                text=ground["text"],
                refs=[EvidenceRefId(ref) for ref in ground.get("refs", [])],
            )
            for ground in row.grounds
        ],
        unknowns=list(row.unknowns),
        next_actions=list(row.next_actions),
        evidence_refs=[EvidenceRefId(value) for value in row.evidence_refs],
        freshness=ArtifactFreshness(row.freshness.value),
        created_by_run_id=(None if row.created_by_run_id is None else RunId(row.created_by_run_id)),
        source_thread_id=(None if row.source_thread_id is None else ThreadId(row.source_thread_id)),
        created_at=row.created_at,
    )


def as_thread_conversation(
    project: ProjectRow, thread_id: ThreadId, run: AgentRunRow | None
) -> ThreadConversationState:
    """Render the stored projection of one thread.

    Messages and activities are the agent service's durable projection, which
    this service does not hold yet, so they are empty rather than invented.
    ``active_run_id`` is filled from the run lifecycle the UI can reconnect to;
    a terminal run is still reported in ``run`` but is not an active target.
    """
    run_info: RunInfo | None = None
    active_run_id: RunId | None = None
    revision = 0
    if run is not None:
        run_info = RunInfo(
            id=RunId(run.id),
            thread_id=thread_id,
            project_id=ProjectId(project.id),
            status=RunStatus(run.status.value),
            started_at=run.started_at,
            finished_at=run.finished_at,
            based_on_context_version=run.based_on_context_version,
            last_public_revision=run.last_public_revision,
        )
        revision = run.last_public_revision
        if run.status in _ACTIVE_RUN_STATUSES:
            active_run_id = RunId(run.id)
    return ThreadConversationState(
        project_id=ProjectId(project.id),
        thread_id=thread_id,
        run=run_info,
        revision=revision,
        messages=[],
        activities=[],
        context_version=project.context_version,
        save_status=SaveStatus.UNSAVED,
        active_run_id=active_run_id,
    )


def as_page[ItemT](items: list[ItemT], *, limit: int, next_cursor: str | None) -> Page[ItemT]:
    """Wrap items in the shared page envelope.

    ``has_more`` follows the cursor: a page is the last one exactly when the
    server has no position to continue from, so an empty page never has to be
    read as proof that a collection is exhausted.
    """
    return Page[ItemT](
        items=items,
        page=PageInfo(limit=limit, next_cursor=next_cursor, has_more=next_cursor is not None),
    )
