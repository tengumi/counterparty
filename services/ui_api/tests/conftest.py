"""Fixtures for the endpoints that need a real PostgreSQL.

An endpoint whose idempotency, tenant isolation and twenty-slot limit have
never run against PostgreSQL is not verified: all three are enforced by the
database, not by the handlers. So these tests are skipped rather than faked
when no database is provided, and the database named by the environment is
treated as disposable — the managed schemas are recreated for the session.

The application opens its own engine inside the test client's event loop, the
way the real process does. The fixtures here use a separate synchronous engine
only to prepare and inspect rows, which keeps the two loops apart.
"""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from counterparty_storage import MANAGED_SCHEMAS, metadata
from counterparty_storage.reports.enums import IngestionStatus
from counterparty_storage.reports.models import (
    Company,
    CompanyProfile,
    ImportBatch,
    ReportSnapshot,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from counterparty_ui_api.app import create_app
from counterparty_ui_api.config import DemoUser, Settings

TEST_DATABASE_URL_ENV = "COUNTERPARTY_TEST_DATABASE_URL"

SignIn = Callable[..., None]
"""Signs one demo identity in on the client of the test."""

ANALYST = DemoUser.model_validate(
    {
        "tenant_id": "00000000-0000-4000-8000-0000000000e1",
        "user_id": "00000000-0000-4000-8000-0000000000a1",
        "display_name": "Демо-аналитик",
    }
)
PARTNER = DemoUser.model_validate(
    {
        "tenant_id": "00000000-0000-4000-8000-0000000000e2",
        "user_id": "00000000-0000-4000-8000-0000000000a2",
        "display_name": "Демо-партнёр",
    }
)

COLLEAGUE = DemoUser.model_validate(
    {
        "tenant_id": str(ANALYST.tenant_id),
        "user_id": "00000000-0000-4000-8000-0000000000a3",
        "display_name": "Демо-коллега",
    }
)


def _async_url(url: str) -> str:
    """Point the URL at the async driver without changing its target."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a disposable PostgreSQL for the endpoint tests."""
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set; database endpoints were not run")
    return _async_url(url)


@pytest.fixture(scope="session")
def schema(database_url: str) -> Iterator[Engine]:
    """Recreate the managed schemas once and drop them afterwards."""
    engine = create_engine(database_url)
    with engine.begin() as connection:
        for name in sorted(MANAGED_SCHEMAS):
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{name}"'))
        metadata.create_all(connection)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            for name in sorted(MANAGED_SCHEMAS):
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
        engine.dispose()


@pytest.fixture
def clean(schema: Engine) -> Iterator[Engine]:
    """Empty every workspace and report table before each test."""
    tables = ", ".join(
        f'"{table.schema}"."{table.name}"' for table in reversed(metadata.sorted_tables)
    )
    with schema.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield schema


@pytest.fixture
def settings(database_url: str) -> Settings:
    """Server-side settings with distinct owners inside and across tenants."""
    return Settings(
        demo_users={"demo-analyst": ANALYST, "demo-partner": PARTNER, "demo-colleague": COLLEAGUE},
        session_cookie_secure=False,
        database_url=database_url,
        internal_token=SecretStr("test-internal-token"),
    )


@pytest.fixture
def client(clean: Engine, settings: Settings) -> Iterator[TestClient]:
    """Run the application against the disposable database."""
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


@pytest.fixture
def sign_in(client: TestClient) -> SignIn:
    """Return a helper that signs one demo identity in on the shared client."""

    def sign(login: str = "demo-analyst") -> None:
        response = client.post("/api/v1/auth/session", json={"login": login})
        assert response.status_code == 201, response.text

    return sign


def add_company(engine: Engine, *, inn: str) -> UUID:
    """Insert one company of the shared corpus, with no snapshot yet."""
    with Session(engine) as session:
        company = Company(id=uuid4(), inn=inn)
        session.add(company)
        session.commit()
        return company.id


def add_snapshot(
    engine: Engine,
    *,
    company_id: UUID,
    reported_at: datetime | None = None,
    short_name: str | None = None,
) -> UUID:
    """Insert one report snapshot for a company and return its id."""
    with Session(engine) as session:
        batch = ImportBatch(
            id=uuid4(),
            file_name="fixture.json",
            sha256=uuid4().hex + uuid4().hex[:32],
            parser_version="test",
        )
        session.add(batch)
        session.flush()
        report = ReportSnapshot(
            id=uuid4(),
            company_id=company_id,
            batch_id=batch.id,
            source_record_id=f"{company_id}/{uuid4().hex[:6]}",
            source_record_jsonb={},
            source_report_at=reported_at or datetime(2026, 9, 5, tzinfo=UTC),
            hash=uuid4().hex + uuid4().hex[:32],
            raw_jsonb={},
            ingestion_status=IngestionStatus.COMPLETE,
        )
        session.add(report)
        session.flush()
        if short_name is not None:
            session.add(CompanyProfile(report_id=report.id, short_name=short_name))
        session.commit()
        return report.id


def add_reported_company(
    engine: Engine, *, inn: str, short_name: str | None = None
) -> tuple[UUID, UUID]:
    """Insert one company together with one snapshot; return both ids."""
    company_id = add_company(engine, inn=inn)
    report_id = add_snapshot(engine, company_id=company_id, short_name=short_name)
    return company_id, report_id
