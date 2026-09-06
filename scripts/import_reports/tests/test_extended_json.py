"""Decoder behaviour on wrappers and on the four source states."""

from datetime import UTC, datetime
from decimal import Decimal

from counterparty_storage.reports import SourceState

from import_reports import (
    MISSING,
    Invalid,
    IssueCode,
    decode,
    json_pointer,
    probe_field,
    probe_section,
)


def test_date_wrapper_becomes_an_aware_utc_instant() -> None:
    """``$date`` keeps the exact instant, not a guessed calendar date."""
    decoded = decode({"reportDate": {"$date": "2026-08-05T21:00:00.000Z"}})
    assert isinstance(decoded.value, dict)
    assert decoded.value["reportDate"] == datetime(2026, 8, 5, 21, 0, tzinfo=UTC)
    assert decoded.is_clean


def test_number_long_stays_an_exact_integer() -> None:
    """``$numberLong`` is parsed exactly; no float ever appears."""
    decoded = decode({"proceeds": {"$numberLong": "9007199254740993"}})
    assert isinstance(decoded.value, dict)
    assert decoded.value["proceeds"] == 9007199254740993
    assert not isinstance(decoded.value["proceeds"], float)


def test_unknown_wrapper_is_reported_and_kept() -> None:
    """An unimplemented wrapper becomes Invalid, never a zero or a drop."""
    decoded = decode({"amount": {"$numberDouble": "1.5"}})
    assert isinstance(decoded.value, dict)
    invalid = decoded.value["amount"]
    assert isinstance(invalid, Invalid)
    assert invalid.raw == {"$numberDouble": "1.5"}
    assert decoded.issues[0].code is IssueCode.UNKNOWN_WRAPPER
    assert decoded.issues[0].source_path == "/amount"


def test_malformed_date_is_invalid_rather_than_absent() -> None:
    """An unparsable date is a different fact from a missing date."""
    decoded = decode({"status": {"date": {"$date": "not-a-date"}}})
    assert decoded.issues[0].code is IssueCode.MALFORMED_DATE
    assert decoded.issues[0].source_path == "/status/date"
    probe = probe_field(decoded.value, "status", "date")
    assert probe.state is SourceState.INVALID
    assert probe.as_value() is None


def test_mixed_wrapper_object_is_flagged_but_data_is_kept() -> None:
    """An ambiguous object is reported without losing its ordinary keys."""
    decoded = decode({"_id": {"$oid": "abc", "ogrn": "1241600001048"}})
    assert decoded.issues[0].code is IssueCode.MIXED_WRAPPER_OBJECT
    assert isinstance(decoded.value, dict)
    assert decoded.value["_id"]["ogrn"] == "1241600001048"


def test_missing_null_empty_zero_and_invalid_are_five_distinct_answers() -> None:
    """The distinction the product depends on is enforced by the probe API."""
    decoded = decode(
        {
            "explicit_null": None,
            "empty_list": [],
            "empty_object": {},
            "zero": 0,
            "broken": {"$numberLong": "not-a-number"},
        }
    )
    document = decoded.value

    assert probe_field(document, "absent").state is SourceState.MISSING
    assert probe_field(document, "absent").value is MISSING
    assert probe_field(document, "explicit_null").state is SourceState.PRESENT_EMPTY
    assert probe_field(document, "empty_list").state is SourceState.PRESENT_EMPTY
    assert probe_field(document, "empty_object").state is SourceState.PRESENT_EMPTY

    zero = probe_field(document, "zero")
    assert zero.state is SourceState.PRESENT
    assert zero.as_decimal() == Decimal(0)

    assert probe_field(document, "broken").state is SourceState.INVALID


def test_empty_aggregate_is_not_a_confirmed_count_of_zero() -> None:
    """``{}`` in an aggregate stays present_empty with no record count."""
    decoded = decode({"arbitrationByStatus": {"plaintiffArbitrationFinished": {}}})
    probe = probe_section(decoded.value, "arbitrationByStatus", "plaintiffArbitrationFinished")
    assert probe.state is SourceState.PRESENT_EMPTY
    assert probe.record_count is None
    assert probe.records == ()


def test_section_probe_counts_records_and_keeps_the_source_path() -> None:
    """A populated section reports its length and where it came from."""
    decoded = decode({"finReports": [{"common": {"year": 2025}}, {"common": {"year": 2024}}]})
    probe = probe_section(decoded.value, "finReports")
    assert probe.state is SourceState.PRESENT
    assert probe.record_count == 2
    assert probe.source_path == "/finReports"


def test_json_pointer_escapes_special_characters() -> None:
    """Pointers stay RFC 6901 compliant for awkward key names."""
    assert json_pointer("finReports", 0, "common", "year") == "/finReports/0/common/year"
    assert json_pointer("a/b", "c~d") == "/a~1b/c~0d"


def test_probe_is_indifferent_to_the_shape_above_it() -> None:
    """Walking through a wrong type reports missing rather than raising."""
    decoded = decode({"baseInfo": "not-an-object"})
    assert probe_field(decoded.value, "baseInfo", "inn").state is SourceState.MISSING
    assert probe_field(decoded.value, "finReports", 3).state is SourceState.MISSING
