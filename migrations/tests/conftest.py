"""Shared fixtures for migration tests."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL_ENV = "COUNTERPARTY_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a disposable PostgreSQL for migration tests.

    The tests are skipped rather than faked when no database is provided: a
    migration that has not actually run against PostgreSQL is not verified.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set; migrations were not run")
    return url


@pytest.fixture
def alembic_config(database_url: str) -> Iterator[Config]:
    """Alembic config pointed at the disposable database."""
    previous = os.environ.get("COUNTERPARTY_DATABASE_URL")
    os.environ["COUNTERPARTY_DATABASE_URL"] = database_url
    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    try:
        yield config
    finally:
        if previous is None:
            os.environ.pop("COUNTERPARTY_DATABASE_URL", None)
        else:
            os.environ["COUNTERPARTY_DATABASE_URL"] = previous


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    """Engine used to inspect the result of a migration."""
    created = create_engine(database_url)
    try:
        yield created
    finally:
        created.dispose()
