"""Repository and Unit of Work behaviour against a real PostgreSQL."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from conftest import SnapshotFactory
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from counterparty_storage import (
    ContextVersionConflictError,
    IdempotencyConflictError,
    NotFoundError,
    ProjectCompanyLimitError,
    ProjectDeletedError,
    TenantScope,
    create_session_factory,
    unit_of_work,
)
from counterparty_storage.reports.models import Company, CompanyProfile, ReportSnapshot
from counterparty_storage.repositories.workspace import Reservation, ReservationOutcome
from counterparty_storage.unit_of_work import AsyncUnitOfWork
from counterparty_storage.workspace.enums import CounterpartyRole, WorkflowStatus
from counterparty_storage.workspace.models import (
    MAX_PROJECT_COMPANIES,
    Project,
    ProjectCompany,
    Tenant,
    Thread,
    User,
)


async def _project(
    uow: AsyncUnitOfWork, owner_id: UUID, title: str = "Counterparty check"
) -> Project:
    return await uow.projects.create(owner_id=owner_id, title=title)


async def test_a_project_starts_at_context_version_zero(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A new check has no deal context yet and no chat by default."""
    project = await _project(uow, owner_id)
    assert project.context_version == 0
    assert project.default_thread_id is None
    assert project.workflow_status is WorkflowStatus.IN_PROGRESS
    assert project.deleted_at is None


async def test_another_tenant_cannot_reach_the_project(
    uow: AsyncUnitOfWork, other_uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A project of one tenant is not addressable from another tenant."""
    project = await _project(uow, owner_id)
    assert await uow.projects.get(project.id) is not None
    assert await other_uow.projects.get(project.id) is None
    with pytest.raises(NotFoundError):
        await other_uow.projects.require(project.id)


async def test_another_tenant_cannot_reach_the_thread(
    uow: AsyncUnitOfWork, other_uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """The same holds one level down, for the chats of that project."""
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    thread = await uow.threads.create(scope, title="First chat")
    assert await uow.threads.get(thread.id) is not None
    assert await other_uow.threads.get(thread.id) is None


async def test_a_scope_of_another_tenant_is_refused(
    uow: AsyncUnitOfWork, other_uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """Handing a repository someone else's project scope is a programming error."""
    project = await _project(uow, owner_id)
    with pytest.raises(ValueError, match="different tenant"):
        await other_uow.threads.list_for_project(uow.scope.project(project.id))


async def test_the_database_refuses_a_thread_of_a_foreign_tenant(
    session: AsyncSession, uow: AsyncUnitOfWork, other_tenant_id: UUID, owner_id: UUID
) -> None:
    """Isolation survives a statement written by hand, not only a repository."""
    project = await _project(uow, owner_id)
    session.add(
        Thread(
            id=uuid4(),
            project_id=project.id,
            tenant_id=other_tenant_id,
            title="Moved tenant",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_renaming_does_not_change_the_deal_context(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A rename is not new information about the deal."""
    project = await _project(uow, owner_id)
    await uow.projects.bump_context_version(project.id, expected=0)
    renamed = await uow.projects.rename(project.id, "Renamed")
    assert renamed.title == "Renamed"
    assert renamed.context_version == 1


async def test_a_stale_context_version_is_refused(uow: AsyncUnitOfWork, owner_id: UUID) -> None:
    """A client that read version 0 cannot overwrite a change it never saw."""
    project = await _project(uow, owner_id)
    assert await uow.projects.bump_context_version(project.id, expected=0) == 1
    with pytest.raises(ContextVersionConflictError) as raised:
        await uow.projects.bump_context_version(project.id, expected=0)
    assert raised.value.actual == 1


async def test_a_deleted_project_accepts_no_writes(uow: AsyncUnitOfWork, owner_id: UUID) -> None:
    """Access closes when deletion is accepted, not when cleanup finishes."""
    project = await _project(uow, owner_id)
    await uow.projects.soft_delete(project.id)
    assert await uow.projects.get(project.id) is None
    assert await uow.projects.get(project.id, include_deleted=True) is not None
    with pytest.raises(ProjectDeletedError):
        await uow.projects.rename(project.id, "Too late")


async def test_projects_are_listed_by_activity(uow: AsyncUnitOfWork, owner_id: UUID) -> None:
    """The tenant's own projects come back, most recently touched first."""
    first = await _project(uow, owner_id, "First")
    second = await _project(uow, owner_id, "Second")
    await uow.projects.bump_context_version(second.id, expected=0)
    listed = await uow.projects.list_recent(limit=10)
    assert next(project.id for project in listed) == second.id
    assert first.id in {project.id for project in listed}


async def test_project_list_filters_owner_and_literal_title(
    session: AsyncSession, uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """List filtering stays tenant scoped and treats search metacharacters literally."""
    another = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="Another")
    session.add(another)
    await session.flush()
    expected = await _project(uow, owner_id, "Поставка 100% хлопка")
    await _project(uow, owner_id, "Поставка хлопка")
    await _project(uow, another.id, "Поставка 100% шерсти")

    listed = await uow.projects.list_recent(
        owner_id=owner_id,
        title_contains="100%",
        limit=10,
    )

    assert [project.id for project in listed] == [expected.id]


async def test_a_company_is_pinned_to_the_snapshot_it_is_judged_on(
    uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """The report the project reasons about does not change under it."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    added = await uow.project_companies.add(
        scope, company_id=company_id, report_id=report_id, role=CounterpartyRole.SUPPLIER
    )
    assert added.created
    assert added.company.report_id == report_id
    assert added.company.slot == 1


async def test_adding_the_same_company_twice_is_not_a_duplicate(
    uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """A repeated add resolves to the row that is already there."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    first = await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    again = await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    assert not again.created
    assert again.company.id == first.company.id
    assert len(await uow.project_companies.list_active(scope)) == 1


async def test_a_project_holds_at_most_twenty_companies(
    session: AsyncSession,
    uow: AsyncUnitOfWork,
    owner_id: UUID,
    new_snapshot: SnapshotFactory,
) -> None:
    """The twenty-first counterparty is refused, per company and per database."""
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    last: ProjectCompany | None = None
    for index in range(MAX_PROJECT_COMPANIES):
        company_id, report_id = await new_snapshot(f"77000000{index:04d}")
        last = (
            await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
        ).company
    assert last is not None
    assert len(await uow.project_companies.list_active(scope)) == MAX_PROJECT_COMPANIES

    extra_company, extra_report = await new_snapshot("779900000001")
    with pytest.raises(ProjectCompanyLimitError):
        await uow.project_companies.add(scope, company_id=extra_company, report_id=extra_report)

    session.add(
        ProjectCompany(
            id=uuid4(),
            project_id=project.id,
            tenant_id=uow.scope.tenant_id,
            company_id=extra_company,
            report_id=extra_report,
            slot=MAX_PROJECT_COMPANIES + 1,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_removing_a_company_keeps_the_report_and_the_history(
    session: AsyncSession, uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """Removal changes the composition, not what was reviewed."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    removed = await uow.project_companies.remove(scope, company_id=company_id)
    assert removed.removed_at is not None
    assert await uow.project_companies.list_active(scope) == []
    assert await session.get(ReportSnapshot, report_id) is not None
    assert await session.get(Company, company_id) is not None
    with pytest.raises(NotFoundError):
        await uow.project_companies.remove(scope, company_id=company_id)


async def test_a_removed_company_can_be_added_again(
    uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """The unique rule covers the active composition, not the history."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    await uow.project_companies.remove(scope, company_id=company_id)
    again = await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    assert again.created
    assert len(await uow.project_companies.list_active(scope)) == 1


async def test_active_compositions_are_loaded_in_a_batch_with_pinned_profiles(
    session: AsyncSession,
    uow: AsyncUnitOfWork,
    owner_id: UUID,
    snapshot: tuple[UUID, UUID],
) -> None:
    """Batch reads keep each membership on its pinned snapshot, not the latest one."""
    company_id, pinned_report_id = snapshot
    session.add(CompanyProfile(report_id=pinned_report_id, short_name="Pinned name"))
    first = await _project(uow, owner_id, "First")
    empty = await _project(uow, owner_id, "Empty")
    await uow.project_companies.add(
        uow.scope.project(first.id), company_id=company_id, report_id=pinned_report_id
    )

    pinned = await session.get(ReportSnapshot, pinned_report_id)
    assert pinned is not None
    newer = ReportSnapshot(
        id=uuid4(),
        company_id=company_id,
        batch_id=pinned.batch_id,
        source_record_id="newer",
        source_record_jsonb={"version": 2},
        source_report_at=datetime(2026, 9, 6, tzinfo=UTC),
        hash=uuid4().hex + uuid4().hex[:32],
        raw_jsonb={},
        ingestion_status=pinned.ingestion_status,
    )
    session.add(newer)
    await session.flush()
    session.add(CompanyProfile(report_id=newer.id, short_name="Newer name"))
    await session.flush()

    grouped = await uow.project_companies.list_active_for_projects([first.id, empty.id])

    assert grouped[empty.id] == []
    assert len(grouped[first.id]) == 1
    record = grouped[first.id][0]
    assert record.membership.report_id == pinned_report_id
    assert record.company.id == company_id
    assert record.profile is not None
    assert record.profile.short_name == "Pinned name"


async def test_the_report_corpus_cannot_be_deleted_while_a_project_pins_it(
    session: AsyncSession, uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """Workspace work never takes a snapshot away from the shared corpus."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            text("DELETE FROM reports.report_snapshots WHERE id = :id"), {"id": report_id}
        )
    await session.rollback()


async def test_deleting_a_project_clears_its_threads_and_composition(
    session: AsyncSession, uow: AsyncUnitOfWork, owner_id: UUID, snapshot: tuple[UUID, UUID]
) -> None:
    """Cleanup removes the project's own rows and leaves the corpus intact."""
    company_id, report_id = snapshot
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    thread = await uow.threads.create(scope, title="Chat")
    await uow.projects.set_default_thread(project.id, thread.id)
    await uow.project_companies.add(scope, company_id=company_id, report_id=report_id)
    await session.flush()

    await session.execute(text("DELETE FROM workspace.projects WHERE id = :id"), {"id": project.id})
    await session.flush()
    threads = await session.execute(select(Thread).where(Thread.project_id == project.id))
    assert threads.scalars().all() == []
    companies = await session.execute(
        select(ProjectCompany).where(ProjectCompany.project_id == project.id)
    )
    assert companies.scalars().all() == []
    assert await session.get(ReportSnapshot, report_id) is not None


async def test_a_thread_carries_its_own_identity_and_activity(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """Archiving records when it happened; restoring clears it."""
    project = await _project(uow, owner_id)
    scope = uow.scope.project(project.id)
    thread = await uow.threads.create(scope, title="Chat")
    archived = await uow.threads.set_archived(thread.id, archived=True)
    assert archived.archived_at is not None
    restored = await uow.threads.set_archived(thread.id, archived=False)
    assert restored.archived_at is None


async def test_a_repeated_request_returns_the_first_resource(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """The retry replays the created project instead of creating a second."""
    request_id = uuid4()
    reservation = await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=request_id,
        request_fingerprint="a" * 64,
        resource_kind="project",
    )
    assert reservation.outcome is ReservationOutcome.STARTED
    project = await _project(uow, owner_id)
    await uow.idempotency.complete(
        scope="projects.create", client_request_id=request_id, resource_id=project.id
    )

    replay = await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=request_id,
        request_fingerprint="a" * 64,
        resource_kind="project",
    )
    assert replay.outcome is ReservationOutcome.REPLAYED
    assert replay.resource_id == project.id
    assert len(await uow.projects.list_recent(limit=10)) == 1


async def test_a_retry_that_arrives_mid_flight_is_told_so(uow: AsyncUnitOfWork) -> None:
    """A second copy of a running request does not start its own work."""
    request_id = uuid4()

    async def reserve() -> Reservation:
        return await uow.idempotency.reserve(
            scope="projects.create",
            client_request_id=request_id,
            request_fingerprint="b" * 64,
            resource_kind="project",
        )

    assert (await reserve()).outcome is ReservationOutcome.STARTED
    second = await reserve()
    assert second.outcome is ReservationOutcome.IN_FLIGHT
    assert second.resource_id is None


async def test_stale_in_flight_takeover_requires_an_explicit_policy(
    session: AsyncSession, uow: AsyncUnitOfWork
) -> None:
    """Age alone changes nothing unless recovery opts into a stale threshold."""
    request_id = uuid4()

    async def reserve(*, stale_after: timedelta | None = None) -> Reservation:
        return await uow.idempotency.reserve(
            scope="projects.create",
            client_request_id=request_id,
            request_fingerprint="9" * 64,
            resource_kind="project",
            stale_after=stale_after,
        )

    await reserve()
    await session.execute(
        text(
            "UPDATE workspace.idempotency_keys"
            " SET created_at = clock_timestamp() - interval '2 hours'"
            " WHERE tenant_id = :tenant AND client_request_id = :request"
        ),
        {"tenant": uow.scope.tenant_id, "request": request_id},
    )

    assert (await reserve()).outcome is ReservationOutcome.IN_FLIGHT
    reclaimed = await reserve(stale_after=timedelta(hours=1))
    assert reclaimed.outcome is ReservationOutcome.STARTED
    assert (await reserve()).outcome is ReservationOutcome.IN_FLIGHT


async def test_only_one_worker_can_take_over_a_stale_reservation(engine: AsyncEngine) -> None:
    """The stale update is conditional, so concurrent recovery has one winner."""
    factory = create_session_factory(engine)
    tenant = Tenant(id=uuid4(), slug=f"stale-{uuid4().hex[:8]}", title="Stale")
    scope = TenantScope(tenant_id=tenant.id)
    request_id = uuid4()
    async with factory() as setup:
        setup.add(tenant)
        await setup.commit()
        async with unit_of_work(factory, scope) as initial:
            await initial.idempotency.reserve(
                scope="projects.create",
                client_request_id=request_id,
                request_fingerprint="6" * 64,
                resource_kind="project",
            )
            await initial.commit()
        await setup.execute(
            text(
                "UPDATE workspace.idempotency_keys"
                " SET created_at = clock_timestamp() - interval '2 hours'"
                " WHERE tenant_id = :tenant AND client_request_id = :request"
            ),
            {"tenant": tenant.id, "request": request_id},
        )
        await setup.commit()

    async def reclaim() -> ReservationOutcome:
        async with unit_of_work(factory, scope) as unit:
            reservation = await unit.idempotency.reserve(
                scope="projects.create",
                client_request_id=request_id,
                request_fingerprint="6" * 64,
                resource_kind="project",
                stale_after=timedelta(hours=1),
            )
            await unit.commit()
            return reservation.outcome

    try:
        outcomes = await asyncio.gather(reclaim(), reclaim())
        assert sorted(outcomes) == [ReservationOutcome.IN_FLIGHT, ReservationOutcome.STARTED]
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                text("DELETE FROM workspace.idempotency_keys WHERE tenant_id = :tenant"),
                {"tenant": tenant.id},
            )
            await cleanup.execute(
                text("DELETE FROM workspace.tenants WHERE id = :tenant"), {"tenant": tenant.id}
            )
            await cleanup.commit()


async def test_release_only_removes_an_unfinished_reservation(
    uow: AsyncUnitOfWork, owner_id: UUID
) -> None:
    """A failed attempt can retry, while a completed replay cannot be erased."""
    failed_id = uuid4()
    await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=failed_id,
        request_fingerprint="7" * 64,
        resource_kind="project",
    )
    assert await uow.idempotency.release(scope="projects.create", client_request_id=failed_id)
    retry = await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=failed_id,
        request_fingerprint="7" * 64,
        resource_kind="project",
    )
    assert retry.outcome is ReservationOutcome.STARTED

    completed_id = uuid4()
    await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=completed_id,
        request_fingerprint="8" * 64,
        resource_kind="project",
    )
    project = await _project(uow, owner_id)
    await uow.idempotency.complete(
        scope="projects.create", client_request_id=completed_id, resource_id=project.id
    )
    assert not await uow.idempotency.release(
        scope="projects.create", client_request_id=completed_id
    )


async def test_reusing_a_request_id_for_another_payload_is_refused(
    uow: AsyncUnitOfWork,
) -> None:
    """Replaying the first result would silently discard the second request."""
    request_id = uuid4()
    await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=request_id,
        request_fingerprint="c" * 64,
        resource_kind="project",
    )
    with pytest.raises(IdempotencyConflictError):
        await uow.idempotency.reserve(
            scope="projects.create",
            client_request_id=request_id,
            request_fingerprint="d" * 64,
            resource_kind="project",
        )


async def test_the_same_request_id_is_free_again_in_another_operation(
    uow: AsyncUnitOfWork,
) -> None:
    """A reservation is per operation, so two endpoints do not collide."""
    request_id = uuid4()
    for scope in ("projects.create", "threads.create"):
        reservation = await uow.idempotency.reserve(
            scope=scope,
            client_request_id=request_id,
            request_fingerprint="e" * 64,
            resource_kind="project",
        )
        assert reservation.outcome is ReservationOutcome.STARTED


async def test_the_same_request_id_is_free_again_in_another_tenant(
    uow: AsyncUnitOfWork, other_uow: AsyncUnitOfWork
) -> None:
    """Two tenants never collide on a client-chosen identifier."""
    request_id = uuid4()

    async def reserve(unit: AsyncUnitOfWork) -> Reservation:
        return await unit.idempotency.reserve(
            scope="projects.create",
            client_request_id=request_id,
            request_fingerprint="f" * 64,
            resource_kind="project",
        )

    assert (await reserve(uow)).outcome is ReservationOutcome.STARTED
    assert (await reserve(other_uow)).outcome is ReservationOutcome.STARTED


async def test_the_database_refuses_a_second_reservation_row(
    session: AsyncSession, uow: AsyncUnitOfWork
) -> None:
    """Idempotency is the primary key, not a check performed in Python."""
    request_id = uuid4()
    await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=request_id,
        request_fingerprint="0" * 64,
        resource_kind="project",
    )
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO workspace.idempotency_keys"
                " (tenant_id, scope, client_request_id, request_fingerprint,"
                "  state, resource_kind)"
                " VALUES (:tenant, 'projects.create', :request, :fingerprint,"
                "  'in_flight', 'project')"
            ),
            {
                "tenant": uow.scope.tenant_id,
                "request": request_id,
                "fingerprint": "0" * 64,
            },
        )
    await session.rollback()


async def test_a_reservation_cannot_be_completed_without_its_resource(
    session: AsyncSession, uow: AsyncUnitOfWork
) -> None:
    """A completed reservation always names what it created."""
    request_id = uuid4()
    await uow.idempotency.reserve(
        scope="projects.create",
        client_request_id=request_id,
        request_fingerprint="1" * 64,
        resource_kind="project",
    )
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "UPDATE workspace.idempotency_keys SET state = 'completed'"
                " WHERE tenant_id = :tenant AND client_request_id = :request"
            ),
            {"tenant": uow.scope.tenant_id, "request": request_id},
        )
    await session.rollback()


async def test_the_unit_of_work_rolls_back_unless_it_commits(engine: AsyncEngine) -> None:
    """Leaving the block without committing leaves no half-written project.

    This one runs on its own connection, outside the test transaction, so the
    rollback it checks is a real one and not an enclosing savepoint.
    """
    factory = create_session_factory(engine)
    tenant = Tenant(id=uuid4(), slug=f"uow-{uuid4().hex[:8]}", title="UoW")
    user = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="UoW")
    async with factory() as setup:
        setup.add_all([tenant, user])
        await setup.commit()
    scope = TenantScope(tenant_id=tenant.id)
    try:
        project_id: UUID
        async with unit_of_work(factory, scope) as uow:
            project = await uow.projects.create(owner_id=user.id, title="Rolled back")
            project_id = project.id
        async with unit_of_work(factory, scope) as reader:
            assert await reader.projects.get(project_id) is None

        async with unit_of_work(factory, scope) as uow:
            kept = await uow.projects.create(owner_id=user.id, title="Committed")
            await uow.commit()
        async with unit_of_work(factory, scope) as reader:
            assert await reader.projects.get(kept.id) is not None
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                text("DELETE FROM workspace.projects WHERE tenant_id = :tenant"),
                {"tenant": tenant.id},
            )
            await cleanup.execute(
                text("DELETE FROM workspace.tenants WHERE id = :tenant"), {"tenant": tenant.id}
            )
            await cleanup.execute(
                text("DELETE FROM workspace.users WHERE id = :user"), {"user": user.id}
            )
            await cleanup.commit()


async def test_the_reports_repositories_are_read_only(
    uow: AsyncUnitOfWork, snapshot: tuple[UUID, UUID]
) -> None:
    """They resolve a company and its newest snapshot and expose no write."""
    company_id, report_id = snapshot
    company = await uow.companies.get(company_id)
    assert company is not None
    assert await uow.companies.get_by_inn(company.inn) is not None
    latest = await uow.report_snapshots.latest_for_company(company_id)
    assert latest is not None
    assert latest.id == report_id
    for repository in (uow.companies, uow.report_snapshots):
        assert not [name for name in dir(repository) if name in {"add", "create", "delete"}]


async def test_company_search_uses_latest_local_profile_and_stable_cursor(
    session: AsyncSession, uow: AsyncUnitOfWork, new_snapshot: SnapshotFactory
) -> None:
    """Search is local, literal, case insensitive, and ordered by INN plus id."""
    first_company, first_report = await new_snapshot("770000000001")
    second_company, second_report = await new_snapshot("770000000002")
    session.add_all(
        [
            CompanyProfile(report_id=first_report, short_name="100% Ромашка"),
            CompanyProfile(report_id=second_report, short_name="Ромашка"),
        ]
    )
    await session.flush()

    literal = await uow.companies.search(query="100%", limit=10)
    assert [row.company.id for row in literal] == [first_company]
    assert literal[0].report is not None and literal[0].report.id == first_report
    assert literal[0].profile is not None

    first_page = await uow.companies.search(query="ромашка", limit=1)
    assert [row.company.id for row in first_page] == [first_company]
    second_page = await uow.companies.search(
        query="РОМАШКА",
        after_inn=first_page[0].company.inn,
        after_id=first_page[0].company.id,
        limit=10,
    )
    assert [row.company.id for row in second_page] == [second_company]
