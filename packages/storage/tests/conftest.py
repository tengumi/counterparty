"""Fixtures for the repository tests that need a real PostgreSQL.

A repository that has never run against PostgreSQL is not verified, so these
tests are skipped rather than faked when no database is provided. The database
named by the environment variable is treated as disposable: the managed schemas
are recreated at the start of the session and dropped at the end.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from counterparty_storage import (
    MANAGED_SCHEMAS,
    TenantScope,
    create_database_engine,
    metadata,
)
from counterparty_storage.reports.enums import IngestionStatus
from counterparty_storage.reports.models import Company, ImportBatch, ReportSnapshot
from counterparty_storage.unit_of_work import AsyncUnitOfWork
from counterparty_storage.workspace.models import Tenant, User

TEST_DATABASE_URL_ENV = "COUNTERPARTY_TEST_DATABASE_URL"


def _async_url(url: str) -> str:
    """Point the URL at the async driver without changing its target."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a disposable PostgreSQL for the repository tests."""
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set; repositories were not run")
    return _async_url(url)


@pytest.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine with the mapped schema created from the models themselves."""
    created = create_database_engine(database_url)
    async with created.begin() as connection:
        for schema in sorted(MANAGED_SCHEMAS):
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(metadata.create_all)
    try:
        yield created
    finally:
        async with created.begin() as connection:
            for schema in sorted(MANAGED_SCHEMAS):
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await created.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose whole transaction is rolled back after the test.

    ``commit`` inside a test is a savepoint release, so a repository can be
    exercised exactly as a service would use it without leaking rows.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        opened = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield opened
        finally:
            await opened.close()
            await transaction.rollback()


@pytest.fixture
async def tenant_id(session: AsyncSession) -> UUID:
    """A tenant with one member, ready to own projects."""
    return await _make_tenant(session, "acme")


@pytest.fixture
async def other_tenant_id(session: AsyncSession) -> UUID:
    """A second tenant, used to prove that nothing crosses the boundary."""
    return await _make_tenant(session, "rival")


async def _make_tenant(session: AsyncSession, slug: str) -> UUID:
    tenant = Tenant(id=uuid4(), slug=slug, title=slug.title())
    session.add(tenant)
    await session.flush()
    return tenant.id


@pytest.fixture
async def owner_id(session: AsyncSession) -> UUID:
    """A user who owns the projects created by the tests."""
    user = User(id=uuid4(), email=f"{uuid4()}@example.test", display_name="Owner")
    session.add(user)
    await session.flush()
    return user.id


SnapshotFactory = Callable[[str], Awaitable[tuple[UUID, UUID]]]


@pytest.fixture
def new_snapshot(session: AsyncSession) -> SnapshotFactory:
    """Factory inserting one company of the shared corpus and one snapshot."""

    async def factory(inn: str) -> tuple[UUID, UUID]:
        return await _make_snapshot(session, inn=inn)

    return factory


@pytest.fixture
async def snapshot(new_snapshot: SnapshotFactory) -> tuple[UUID, UUID]:
    """One company of the shared corpus and one of its snapshots."""
    return await new_snapshot("7449088645")


async def _make_snapshot(session: AsyncSession, *, inn: str) -> tuple[UUID, UUID]:
    """Insert a company and one report snapshot; return their ids."""
    batch = ImportBatch(
        id=uuid4(),
        file_name="fixture.json",
        sha256=uuid4().hex + uuid4().hex[:32],
        parser_version="test",
    )
    company = Company(id=uuid4(), inn=inn)
    session.add_all([batch, company])
    await session.flush()
    report = ReportSnapshot(
        id=uuid4(),
        company_id=company.id,
        batch_id=batch.id,
        source_record_id=f"{inn}/2026",
        source_record_jsonb={"inn": inn},
        source_report_at=datetime(2026, 9, 5, tzinfo=UTC),
        hash=uuid4().hex + uuid4().hex[:32],
        raw_jsonb={},
        ingestion_status=IngestionStatus.COMPLETE,
    )
    session.add(report)
    await session.flush()
    return company.id, report.id


@pytest.fixture
def uow(session: AsyncSession, tenant_id: UUID) -> AsyncUnitOfWork:
    """Unit of work bound to the first tenant."""
    return AsyncUnitOfWork(session, TenantScope(tenant_id=tenant_id))


@pytest.fixture
def other_uow(session: AsyncSession, other_tenant_id: UUID) -> AsyncUnitOfWork:
    """Unit of work bound to the second tenant, sharing the same session."""
    return AsyncUnitOfWork(session, TenantScope(tenant_id=other_tenant_id))
