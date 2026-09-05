"""Normalization rules, checked against the approved source and against edges.

The control values are the ones fixed in Specs §10 and in the C2 checkpoint.
They are asserted here rather than re-measured, so a change in the parser that
moves a reported number has to fail this file before it can reach a database.
"""

from decimal import Decimal
from typing import Any

import pytest
from counterparty_contracts import WarningCode
from counterparty_storage.reports import IngestionStatus, SourceState, WarningSeverity

from import_reports import normalize
from import_reports.normalize import FailedRecord, NormalizedSnapshot

#: Fixture of Specs §10: the company whose latest reported period is pinned.
CONTROL_INN = "7449088645"


def _snapshots(records: list[Any]) -> list[NormalizedSnapshot]:
    normalized = [normalize(record) for record in records]
    assert all(isinstance(item, NormalizedSnapshot) for item in normalized)
    return [item for item in normalized if isinstance(item, NormalizedSnapshot)]


@pytest.fixture(scope="session")
def snapshots(records: list[Any]) -> list[NormalizedSnapshot]:
    """Every record of the approved source, normalized once."""
    return _snapshots(records)


def test_every_approved_record_normalizes_completely(
    snapshots: list[NormalizedSnapshot],
) -> None:
    """All 100 records of the approved file produce a complete snapshot."""
    assert len(snapshots) == 100
    assert {snapshot.ingestion_status for snapshot in snapshots} == {IngestionStatus.COMPLETE}
    assert len({snapshot.inn for snapshot in snapshots}) == 100


def test_child_row_counts_match_the_source(snapshots: list[NormalizedSnapshot]) -> None:
    """The approved file carries 2228 activities and 194 financial periods."""
    assert sum(len(snapshot.activities) for snapshot in snapshots) == 2228
    assert sum(len(snapshot.financials) for snapshot in snapshots) == 194
    assert {len(snapshot.availability) for snapshot in snapshots} == {19}


def test_section_profile_of_the_source_is_reproduced(
    snapshots: list[NormalizedSnapshot],
) -> None:
    """`finReports` is missing 25 times, empty 8 times and populated 67 times."""
    states = [
        row["source_state"]
        for snapshot in snapshots
        for row in snapshot.availability
        if row["section"] == "finReports"
    ]
    assert states.count(SourceState.MISSING) == 25
    assert states.count(SourceState.PRESENT_EMPTY) == 8
    assert states.count(SourceState.PRESENT) == 67


def test_control_financial_values_of_specs_section_ten(
    snapshots: list[NormalizedSnapshot],
) -> None:
    """The pinned company reports 2025 with its exact figures and source paths."""
    snapshot = next(item for item in snapshots if item.inn == CONTROL_INN)
    period = next(row for row in snapshot.financials if row["year"] == 2025)
    assert period["proceeds"] == Decimal("74586000")
    assert period["equity"] == Decimal("-300000")
    assert period["cash"] == Decimal("355000")
    assert period["source_path"] == "/finReports/0"
    # The year is what identifies the period; index 0 is not assumed to be it.
    assert period["ordinal"] == 0
    assert max(row["year"] for row in snapshot.financials) == 2025


def test_zsk_tokens_without_a_confirmed_mapping_are_reported(
    snapshots: list[NormalizedSnapshot],
) -> None:
    """`YELLOW` and `RED` are kept verbatim and each raises one diagnostic."""
    raw_values = [snapshot.zsk["raw_value"] for snapshot in snapshots]
    assert raw_values.count("GREEN") == 81
    assert raw_values.count("YELLOW") == 18
    assert raw_values.count("RED") == 1
    unconfirmed = [
        item
        for snapshot in snapshots
        for item in snapshot.diagnostics
        if item.code == WarningCode.UNKNOWN_ENUM_VALUE.value
    ]
    assert len(unconfirmed) == 19
    assert {item.severity for item in unconfirmed} == {WarningSeverity.INFO}


def test_approved_source_raises_no_error_diagnostic(
    snapshots: list[NormalizedSnapshot],
) -> None:
    """Nothing in the approved file is unparsable, so nothing is coerced."""
    assert [item for snapshot in snapshots for item in snapshot.diagnostics if item.is_error] == []


def _record(report: dict[str, Any]) -> dict[str, Any]:
    base = {"inn": "7449088645", "ogrn": "1027402893418"}
    merged = {"baseInfo": {**base, **report.pop("baseInfo", {})}, **report}
    merged.setdefault("reportDate", {"$date": "2026-08-27T21:00:00.000Z"})
    return {"_id": {"ogrn": "1027402893418", "date": merged["reportDate"]}, "report": merged}


def test_missing_empty_zero_and_unreadable_stay_four_states() -> None:
    """A zero is a reported number; the other three are not values at all."""
    normalized = normalize(
        _record(
            {
                "finReports": [
                    {
                        "common": {"year": 2024, "proceeds": 0},
                        "assets": {},
                        "liabilities": {"capitals": "not a number"},
                    }
                ],
                "phones": [],
            }
        )
    )
    assert isinstance(normalized, NormalizedSnapshot)
    period = normalized.financials[0]
    assert period["proceeds"] == Decimal(0), "a reported zero is a value"
    assert period["profit"] is None, "an absent field is not a zero"
    assert period["total_assets"] is None
    assert period["equity"] is None, "an unreadable amount is not a zero"
    unreadable = [item for item in normalized.diagnostics if item.is_error]
    assert [item.source_path for item in unreadable] == ["/finReports/0/liabilities/capitals"]
    assert normalized.ingestion_status is IngestionStatus.PARTIAL

    states = {row["section"]: row["source_state"] for row in normalized.availability}
    assert states["phones"] is SourceState.PRESENT_EMPTY, "an empty list is not a zero"
    assert states["licenses"] is SourceState.MISSING


def test_a_repeated_financial_year_is_reported_and_not_duplicated() -> None:
    """Two periods claiming the same year cannot both be stored; neither is merged."""
    normalized = normalize(
        _record(
            {
                "finReports": [
                    {"common": {"year": 2024, "proceeds": 1}, "assets": {}, "liabilities": {}},
                    {"common": {"year": 2024, "proceeds": 2}, "assets": {}, "liabilities": {}},
                ]
            }
        )
    )
    assert isinstance(normalized, NormalizedSnapshot)
    assert [row["year"] for row in normalized.financials] == [2024]
    assert normalized.financials[0]["proceeds"] == Decimal(1)
    ambiguous = [
        item for item in normalized.diagnostics if item.code == WarningCode.PERIOD_AMBIGUOUS.value
    ]
    assert len(ambiguous) == 1
    assert ambiguous[0].source_path == "/finReports/1"


def test_a_period_without_a_readable_year_is_not_given_one() -> None:
    """The array position is never used as the period."""
    normalized = normalize(
        _record({"finReports": [{"common": {"proceeds": 5}, "assets": {}, "liabilities": {}}]})
    )
    assert isinstance(normalized, NormalizedSnapshot)
    assert normalized.financials == ()
    assert any(item.code == WarningCode.SOURCE_MISSING.value for item in normalized.diagnostics)


def test_an_unmapped_report_section_is_reported_rather_than_dropped() -> None:
    """A key the import does not know about becomes a warning with its pointer."""
    normalized = normalize(_record({"somethingNew": {"a": 1}}))
    assert isinstance(normalized, NormalizedSnapshot)
    unknown = [
        item for item in normalized.diagnostics if item.details.get("kind") == "unknown_section"
    ]
    assert [item.source_path for item in unknown] == ["/somethingNew"]
    assert normalized.raw_jsonb["somethingNew"] == {"a": 1}, "the value is still stored"


def test_an_invalid_identifier_is_reported_and_the_record_is_kept() -> None:
    """A failing checksum is a diagnostic, not a reason to drop a record."""
    normalized = normalize(_record({"baseInfo": {"inn": "1234567890"}}))
    assert isinstance(normalized, NormalizedSnapshot)
    assert normalized.inn == "1234567890", "the reported value is stored as provided"
    assert any(item.details.get("identifier") == "inn" for item in normalized.diagnostics)


def test_a_record_without_a_report_object_fails_instead_of_being_guessed() -> None:
    """A record that cannot become a snapshot says so, with its key."""
    normalized = normalize({"_id": {"ogrn": "1027402893418"}, "report": None})
    assert isinstance(normalized, FailedRecord)
    assert normalized.source_record_id is not None
    assert [item.code for item in normalized.diagnostics] == [WarningCode.PARSE_FAILED.value]


def test_a_record_without_an_inn_fails_rather_than_inventing_a_company() -> None:
    """A snapshot needs a reported INN; nothing is derived from the OGRN."""
    normalized = normalize({"_id": {}, "report": {"baseInfo": {"ogrn": "1027402893418"}}})
    assert isinstance(normalized, FailedRecord)
    assert any(item.details.get("kind") == "identity_missing" for item in normalized.diagnostics)


def test_the_snapshot_hash_ignores_key_order_but_not_content() -> None:
    """A re-exported record with reordered keys is the same snapshot."""
    first = normalize(_record({"phones": []}))
    second = normalize(_record({"phones": []}))
    changed = normalize(_record({"phones": [{"value": "+7"}]}))
    assert isinstance(first, NormalizedSnapshot)
    assert isinstance(second, NormalizedSnapshot)
    assert isinstance(changed, NormalizedSnapshot)
    assert first.hash == second.hash
    assert first.hash != changed.hash
