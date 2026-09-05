"""Decimal, integer and date parsing with explicit availability."""

from datetime import UTC, date, datetime
from decimal import Decimal

from counterparty_domain import (
    Availability,
    FactSlot,
    format_decimal,
    is_zero,
    parse_date,
    parse_decimal,
    parse_fiscal_year,
    parse_integer,
    quantize_money,
    sum_decimals,
)


def test_decimal_string_from_contract_is_parsed_exactly() -> None:
    """Wire decimals keep their scale and never pass through float."""
    slot = parse_decimal("1920000.00")
    assert slot.unwrap() == Decimal("1920000.00")
    assert format_decimal(slot.unwrap()) == "1920000.00"


def test_zero_string_is_available_while_none_is_missing() -> None:
    """``"0"`` is a value; ``None`` is not."""
    zero = parse_decimal("0")
    assert is_zero(zero)
    missing = parse_decimal(None)
    assert missing.availability is Availability.MISSING
    assert not is_zero(missing)


def test_empty_string_is_present_empty_not_zero() -> None:
    """An empty source string is distinguishable from both zero and missing."""
    slot = parse_decimal("")
    assert slot.availability is Availability.PRESENT_EMPTY
    assert not is_zero(slot)


def test_malformed_number_stays_invalid_not_zero() -> None:
    """Import must warn about malformed numbers, not read them as zero."""
    for raw in ("1 920 000", "1,920,000.00", "abc", "1e6", "--5"):
        slot = parse_decimal(raw)
        assert slot.availability is Availability.INVALID, raw
        assert not is_zero(slot)


def test_float_and_bool_are_rejected_for_money() -> None:
    """Binary floats and booleans are never accepted as monetary values."""
    assert parse_decimal(0.1).availability is Availability.INVALID
    assert parse_decimal(True).availability is Availability.INVALID
    assert parse_decimal(Decimal("NaN")).availability is Availability.INVALID


def test_negative_and_int_inputs() -> None:
    """Negative capital is a legitimate value, not an error."""
    assert parse_decimal("-300000").unwrap() == Decimal("-300000")
    assert parse_decimal(74586000).unwrap() == Decimal(74586000)


def test_integer_parsing_states() -> None:
    """Integers keep the same missing/empty/invalid distinctions."""
    assert parse_integer("12").unwrap() == 12
    assert parse_integer(Decimal("12.0")).unwrap() == 12
    assert parse_integer(Decimal("12.5")).availability is Availability.INVALID
    assert parse_integer("12.5").availability is Availability.INVALID
    assert parse_integer(None).availability is Availability.MISSING
    assert parse_integer(" ").availability is Availability.PRESENT_EMPTY


def test_date_parsing_states() -> None:
    """Calendar dates are ISO-only; nonsense dates stay invalid."""
    assert parse_date("2025-01-31").unwrap() == date(2025, 1, 31)
    assert parse_date("2025-02-30").availability is Availability.INVALID
    assert parse_date("31.01.2025").availability is Availability.INVALID
    assert parse_date(None).availability is Availability.MISSING
    assert parse_date("").availability is Availability.PRESENT_EMPTY


def test_datetime_is_truncated_with_a_warning() -> None:
    """A timestamp used as a calendar date is flagged, not silently accepted."""
    slot = parse_date(datetime(2025, 3, 1, 22, 30, tzinfo=UTC))
    assert slot.unwrap() == date(2025, 3, 1)
    assert slot.warnings


def test_fiscal_year_is_an_integer_in_range() -> None:
    """A financial year is a year, never a report date."""
    assert parse_fiscal_year(2025).unwrap() == 2025
    assert parse_fiscal_year("2025").unwrap() == 2025
    assert parse_fiscal_year(20250).availability is Availability.INVALID
    assert parse_fiscal_year("2025-01-01").availability is Availability.INVALID


def test_quantize_money_rounds_half_up() -> None:
    """Monetary rounding is half-up, not banker's rounding."""
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")
    assert quantize_money(Decimal("2.355")) == Decimal("2.36")
    assert quantize_money(Decimal("-2.345")) == Decimal("-2.35")


def test_sum_refuses_to_treat_unknown_parts_as_zero() -> None:
    """One unknown component makes the whole total unknown."""
    known = [parse_decimal("10.00"), parse_decimal("2.50")]
    total = sum_decimals(known)
    assert total.unwrap() == Decimal("12.50")

    partial = sum_decimals([*known, parse_decimal(None)])
    assert partial.availability is Availability.MISSING
    assert partial.value is None


def test_empty_sum_is_present_empty_not_zero() -> None:
    """Nothing to sum is not a confirmed zero total."""
    total = sum_decimals([])
    assert total.availability is Availability.PRESENT_EMPTY
    assert not is_zero(total)


def test_sum_collects_evidence_of_its_components() -> None:
    """A derived total carries the references of the values it used."""
    components = [
        FactSlot[Decimal].available(Decimal("1"), evidence_refs=("ev-1",)),
        FactSlot[Decimal].available(Decimal("2"), evidence_refs=("ev-2", "ev-1")),
    ]
    total = sum_decimals(components)
    assert total.evidence_refs == ("ev-1", "ev-2")
