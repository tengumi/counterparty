"""User decisions, AI artifacts and the UI's read of run lifecycle."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from counterparty_storage import ProjectDeletedError
from counterparty_storage.unit_of_work import AsyncUnitOfWork
from counterparty_storage.workspace.enums import (
    AgentRunStatus,
    ArtifactFreshness,
    DecisionOutcome,
)
from counterparty_storage.workspace.models import AgentRun


async def _project_and_thread(uow: AsyncUnitOfWork, owner_id: UUID) -> tuple[UUID, UUID]:
    project = await uow.projects.create(owner_id=owner_id, title="Check")
    thread = await uow.threads.create(uow.scope.project(project.id), title="First chat")
    return project.id, thread.id


async def test_a_decision_is_recorded_and_listed_newest_first(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """Two decisions of one project come back with the newer one first."""
    project_id, _ = await _project_and_thread(uow, owner_id)
    scope = uow.scope.project(project_id)

    first = await uow.decisions.record(
        scope,
        author_user_id=owner_id,
        outcome=DecisionOutcome.NOT_READY,
        rationale="Too many open proceedings",
        conditions=[],
        company_ids=[],
        context_version=0,
        evidence_refs=[],
    )
    second = await uow.decisions.record(
        scope,
        author_user_id=owner_id,
        outcome=DecisionOutcome.READY_WITH_CONDITIONS,
        rationale="Acceptable with a bank guarantee",
        conditions=["Bank guarantee for the advance"],
        company_ids=[uuid4()],
        context_version=1,
        evidence_refs=["report/abc#/field"],
        supersedes_id=first.id,
    )

    listed = await uow.decisions.list_for_project(scope)
    assert [row.id for row in listed] == [second.id, first.id]
    assert listed[0].author_user_id == owner_id
    assert listed[0].supersedes_id == first.id
    assert listed[0].conditions == ["Bank guarantee for the advance"]


async def test_a_decision_needs_a_project_that_still_accepts_writes(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A deleted project records no further decision."""
    project_id, _ = await _project_and_thread(uow, owner_id)
    await uow.projects.soft_delete(project_id)

    with pytest.raises(ProjectDeletedError):
        await uow.decisions.record(
            uow.scope.project(project_id),
            author_user_id=owner_id,
            outcome=DecisionOutcome.READY,
            rationale="n/a",
            conditions=[],
            company_ids=[],
            context_version=0,
            evidence_refs=[],
        )


async def test_another_tenant_cannot_read_a_decision(
    uow: AsyncUnitOfWork, other_uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A decision is not addressable from another tenant's repository."""
    project_id, _ = await _project_and_thread(uow, owner_id)
    await uow.decisions.record(
        uow.scope.project(project_id),
        author_user_id=owner_id,
        outcome=DecisionOutcome.READY,
        rationale="Fine",
        conditions=[],
        company_ids=[],
        context_version=0,
        evidence_refs=[],
    )

    with pytest.raises(ValueError, match="different tenant"):
        await other_uow.decisions.list_for_project(uow.scope.project(project_id))


async def test_only_the_latest_version_of_each_artifact_is_returned(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """``latest_only`` collapses versions and keeps the newest artifact first."""
    project_id, thread_id = await _project_and_thread(uow, owner_id)
    scope = uow.scope.project(project_id)
    artifact_id = uuid4()

    await uow.artifacts.add_version(
        scope,
        artifact_id=artifact_id,
        version=1,
        based_on_context_version=0,
        question="Can we pay 80% upfront?",
        summary="Draft answer",
        source_thread_id=thread_id,
    )
    await uow.artifacts.add_version(
        scope,
        artifact_id=artifact_id,
        version=2,
        based_on_context_version=1,
        question="Can we pay 80% upfront?",
        summary="Revised answer",
        freshness=ArtifactFreshness.CURRENT,
        source_thread_id=thread_id,
    )
    other_id = uuid4()
    await uow.artifacts.add_version(
        scope,
        artifact_id=other_id,
        version=1,
        based_on_context_version=1,
        question="Another question",
        summary="Only version",
        source_thread_id=thread_id,
    )

    latest = await uow.artifacts.list_for_project(scope, latest_only=True)
    assert {(row.id, row.version) for row in latest} == {(artifact_id, 2), (other_id, 1)}
    everything = await uow.artifacts.list_for_project(scope)
    assert len(everything) == 3


async def test_the_ui_reads_the_latest_run_of_a_thread(
    session: AsyncSession, uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """The newest run of the thread is what the UI offers to reconnect to."""
    project_id, thread_id = await _project_and_thread(uow, owner_id)
    scope = uow.scope.project(project_id)
    assert await uow.agent_runs.latest_for_thread(scope, thread_id) is None

    older = AgentRun(
        id=uuid4(),
        tenant_id=uow.scope.tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        owner_id=uuid4(),
        client_request_id=uuid4(),
        status=AgentRunStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        finished_at=datetime.now(UTC) - timedelta(minutes=4),
    )
    newer = AgentRun(
        id=uuid4(),
        tenant_id=uow.scope.tenant_id,
        project_id=project_id,
        thread_id=thread_id,
        owner_id=uuid4(),
        client_request_id=uuid4(),
        status=AgentRunStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    session.add_all([older, newer])
    await session.flush()

    found = await uow.agent_runs.latest_for_thread(scope, thread_id)
    assert found is not None and found.id == newer.id
