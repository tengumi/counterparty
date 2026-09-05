"""Control checks against the approved snapshot itself.

These pin the decoder to the file the contract was agreed on: the exact bytes,
the exact shape, and the numeric fixture named in the system contracts. If the
source is replaced, they fail loudly instead of letting the import reinterpret
new data with old assumptions.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from counterparty_storage.reports import SourceState

from import_reports import (
    APPROVED_FILE_SHA256,
    APPROVED_RECORD_COUNT,
    APPROVED_SCHEMA_FINGERPRINT,
    SUPPORTED_WRAPPERS,
    decode,
    file_digest,
    observed_shape,
    probe_field,
    probe_section,
    schema_fingerprint,
    snapshot_digest,
    verify_source,
)
from import_reports.inspection import summarize

FIXTURE_INN = "7449088645"


@pytest.fixture(scope="session")
def fixture_report(records: list[Any]) -> dict[str, Any]:
    """The decoded report of the INN used by the system contracts fixture."""
    for record in records:
        decoded = decode(record)
        assert isinstance(decoded.value, dict)
        report = decoded.value["report"]
        if report["baseInfo"]["inn"] == FIXTURE_INN:
            assert isinstance(report, dict)
            return report
    raise AssertionError(f"INN {FIXTURE_INN} is absent from the approved source")


def test_file_digest_matches_the_approved_snapshot(source_path: Path) -> None:
    """The tests below describe these exact bytes."""
    assert file_digest(source_path) == APPROVED_FILE_SHA256


def test_record_count_and_schema_fingerprint_are_unchanged(
    source_path: Path, records: list[Any]
) -> None:
    """Shape drift in the source is detected before any row is written."""
    verification = verify_source(source_path, records)
    assert verification.record_count == APPROVED_RECORD_COUNT
    assert verification.schema_digest == APPROVED_SCHEMA_FINGERPRINT
    assert verification.is_approved_source
    assert verification.differences == ()


def test_only_two_wrappers_occur_in_the_approved_source(records: list[Any]) -> None:
    """Every ``$``-wrapper in the file is one this decoder implements."""
    wrappers = {
        type_name
        for types in observed_shape(records).values()
        for type_name in types
        if type_name.startswith("$")
    }
    assert wrappers == set(SUPPORTED_WRAPPERS)


def test_the_whole_source_decodes_without_a_single_issue(records: list[Any]) -> None:
    """No unknown wrapper, malformed number or float reaches the importer."""
    issues = [issue for record in records for issue in decode(record).issues]
    assert issues == []


def test_control_values_of_the_contracts_fixture(fixture_report: dict[str, Any]) -> None:
    """The numeric fixture of the system contracts survives decoding exactly."""
    period = probe_section(fixture_report, "finReports").records[0]

    year = probe_field(period, "common", "year", base_path="/finReports/0")
    proceeds = probe_field(period, "common", "proceeds", base_path="/finReports/0")
    capitals = probe_field(period, "liabilities", "capitals", base_path="/finReports/0")
    bankroll = probe_field(period, "assets", "currentAssets", "bankroll", base_path="/finReports/0")

    assert year.as_value() == 2025
    assert proceeds.as_decimal() == Decimal(74586000)
    assert capitals.as_decimal() == Decimal(-300000)
    assert bankroll.as_decimal() == Decimal(355000)

    assert proceeds.source_path == "/finReports/0/common/proceeds"
    assert capitals.source_path == "/finReports/0/liabilities/capitals"
    assert bankroll.source_path == "/finReports/0/assets/currentAssets/bankroll"


def test_latest_period_is_chosen_by_year_not_by_array_position(
    fixture_report: dict[str, Any],
) -> None:
    """Index 0 is not trusted to be the latest period; the year decides."""
    periods = probe_section(fixture_report, "finReports").records
    years = [probe_field(period, "common", "year").as_value() for period in periods]
    assert max(year for year in years if isinstance(year, int)) == 2025


def test_negative_equity_is_kept_as_a_number(fixture_report: dict[str, Any]) -> None:
    """A negative reported equity is data, not an error and not a verdict."""
    period = probe_section(fixture_report, "finReports").records[0]
    capitals = probe_field(period, "liabilities", "capitals")
    assert capitals.state is SourceState.PRESENT
    amount = capitals.as_decimal()
    assert amount is not None
    assert amount < 0


def test_zsk_level_is_read_as_a_raw_value(fixture_report: dict[str, Any]) -> None:
    """The external signal is returned verbatim; no colour is derived here."""
    zsk = probe_field(fixture_report, "zskRiskLevel")
    assert zsk.state is SourceState.PRESENT
    assert zsk.as_value() in {"GREEN", "YELLOW", "RED"}


def test_snapshot_digest_is_stable_and_identifies_each_record(records: list[Any]) -> None:
    """Re-reading the same record yields the same idempotency digest."""
    digests = [snapshot_digest(record) for record in records]
    assert len(set(digests)) == APPROVED_RECORD_COUNT
    assert digests[0] == snapshot_digest(records[0])


def test_composite_source_id_agrees_with_the_report(records: list[Any]) -> None:
    """``_id`` is a composite key here, and it matches the report it labels."""
    for record in records:
        decoded = decode(record)
        assert isinstance(decoded.value, dict)
        identity = decoded.value["_id"]
        report = decoded.value["report"]
        assert identity["ogrn"] == report["baseInfo"]["ogrn"]
        assert identity["date"] == report["reportDate"]
        assert isinstance(identity["date"], datetime)
        assert identity["date"].tzinfo == UTC


def test_section_states_match_the_documented_source_profile(
    source_path: Path, records: list[Any]
) -> None:
    """Absent, empty and populated counts equal the agreed data profile."""
    summary = summarize(source_path, records)
    states = summary.section_states

    assert states["finReports"] == {"missing": 25, "present_empty": 8, "present": 67}
    assert states["phones"] == {"present_empty": 71, "present": 29}
    assert states["executionProceedings"] == {"present_empty": 47, "present": 53}
    assert states["licenses"] == {"missing": 91, "present": 9}
    assert states["arbitrationCases"] == {"missing": 56, "present": 44}
    assert states["procurements"] == {"present_empty": 92, "present": 8}
    assert states["branchesInfo"] == {"missing": 98, "present": 2}
    assert states["zskRiskLevel"] == {"present": 100}
    assert summary.unknown_sections == {}
    assert summary.decode_issues == {}
    assert summary.unique_snapshot_digests == APPROVED_RECORD_COUNT


def test_a_reshaped_source_is_reported_as_a_difference(
    source_path: Path, records: list[Any]
) -> None:
    """A new field changes the fingerprint, so drift cannot pass unnoticed."""
    mutated = [{**records[0], "unexpected": {"$numberDouble": "1.0"}}, *records[1:]]
    assert schema_fingerprint(mutated).digest != APPROVED_SCHEMA_FINGERPRINT
    verification = verify_source(source_path, mutated)
    assert any("schema fingerprint" in difference for difference in verification.differences)
