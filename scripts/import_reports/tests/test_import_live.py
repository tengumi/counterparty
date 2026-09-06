"""The import against a real PostgreSQL, including its second run.

Idempotence cannot be demonstrated without a database: the guarantee lives in
two unique constraints, and only the server can enforce them. These tests
therefore skip — loudly and explicitly, never by pretending to pass — unless
``COUNTERPARTY_TEST_DATABASE_URL`` names a migrated database.

Use a database of your own for them. They write the whole corpus, and sharing
one with the schema tests of ``packages/storage`` would leave both confused
about what is stored.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from import_reports.importer import create_import_engine
from import_reports.run import run_import

DATABASE_URL_ENV = "COUNTERPARTY_TEST_DATABASE_URL"

pytestmark = pytest.mark.skipif(
    not os.environ.get(DATABASE_URL_ENV),
    reason=f"set {DATABASE_URL_ENV} to a migrated database to run the import against it",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of the database these tests are allowed to write into."""
    url = os.environ.get(DATABASE_URL_ENV)
    assert url, "guarded by pytestmark"
    return url


def _scalar(database_url: str, statement: str) -> Any:
    engine = create_import_engine(database_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement)).scalar_one()
    finally:
        engine.dispose()


def test_the_second_run_of_the_same_file_changes_nothing(
    source_path: Path, database_url: str
) -> None:
    """A re-import skips every record and leaves every row count identical."""
    first = run_import(source_path, database_url=database_url)
    assert first.records["total"] == 100
    assert first.records["failed"] == 0

    second = run_import(source_path, database_url=database_url)
    assert second.batch_id == first.batch_id, "the same file continues the same batch"
    assert second.batch_reused is True
    assert second.records["imported"] == 0
    assert second.records["skipped"] == 100
    assert second.records["companies_created"] == 0
    assert second.warnings["written"] == 0, "a skipped snapshot re-emits no diagnostic"
    assert second.rows_before == second.rows_after
    assert second.changed_nothing
    assert second.rows_after == first.rows_after


def test_the_corpus_is_stored_whole(source_path: Path, database_url: str) -> None:
    """Every record, every activity and every financial period reaches a row."""
    run_import(source_path, database_url=database_url)
    assert _scalar(database_url, "SELECT count(*) FROM reports.companies") >= 100
    assert (
        _scalar(
            database_url,
            "SELECT count(*) FROM reports.section_availability a "
            "JOIN reports.report_snapshots s ON s.id = a.report_id",
        )
        >= 1900
    ), "19 sections are accounted for on every snapshot"
    assert (
        _scalar(
            database_url,
            "SELECT count(*) FROM reports.report_snapshots WHERE ingestion_status <> 'complete'",
        )
        == 0
    )


def test_the_control_values_of_specs_section_ten_are_readable_back(
    source_path: Path, database_url: str
) -> None:
    """The pinned company's 2025 figures survive the round trip exactly."""
    run_import(source_path, database_url=database_url)
    row = _scalar(
        database_url,
        """
        SELECT json_build_object(
            'year', f.year,
            'proceeds', f.proceeds::text,
            'equity', f.equity::text,
            'cash', f.cash::text,
            'source_path', f.source_path
        )::text
        FROM reports.financial_statements f
        JOIN reports.report_snapshots s ON s.id = f.report_id
        JOIN reports.companies c ON c.id = s.company_id
        WHERE c.inn = '7449088645' AND f.year = 2025
        """,
    )
    # Money is read back as text on purpose: routing an exact NUMERIC through a
    # JSON number would compare a float against the reported amount.
    values = json.loads(row)
    assert values["proceeds"] == "74586000.00"
    assert values["equity"] == "-300000.00"
    assert values["cash"] == "355000.00"
    assert values["source_path"] == "/finReports/0"


def test_a_changed_snapshot_lands_as_a_new_version(
    source_path: Path, database_url: str, tmp_path: Path
) -> None:
    """A record whose content changed is a new version, not a second company."""
    run_import(source_path, database_url=database_url)
    companies_before = _scalar(database_url, "SELECT count(*) FROM reports.companies")
    snapshots_before = _scalar(database_url, "SELECT count(*) FROM reports.report_snapshots")

    records = json.loads(source_path.read_text(encoding="utf-8"))
    # A distinct instant per run, so the test states something new every time
    # instead of quietly re-asserting a version an earlier run already stored.
    later = {"$date": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")}
    records[0]["report"]["reportDate"] = later
    records[0]["_id"]["date"] = later
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    result = run_import(changed, database_url=database_url)
    assert result.records["imported"] == 1
    assert result.records["skipped"] == 99
    assert result.records["companies_created"] == 0
    assert result.source["differences"] == ["file_sha256 differs from the approved snapshot"]
    assert _scalar(database_url, "SELECT count(*) FROM reports.companies") == companies_before
    assert (
        _scalar(database_url, "SELECT count(*) FROM reports.report_snapshots")
        == snapshots_before + 1
    )


def test_the_import_holds_no_delete_privilege(database_url: str) -> None:
    """The role the import connects as cannot remove a stored snapshot.

    This is the check that the run really happened as ``counterparty_importer``
    and not as an owner or a superuser.
    """
    engine = create_import_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT has_table_privilege('reports.report_snapshots', 'DELETE') "
                    "AS can_delete, "
                    "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_super"
                )
            ).one()
    finally:
        engine.dispose()
    assert row.can_delete is False, "the importer must not be able to delete a snapshot"
    assert row.is_super is False, "the import must not run as a superuser"
