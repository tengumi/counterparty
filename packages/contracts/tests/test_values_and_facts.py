"""Money, decimals and the availability semantics of one public fact."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from counterparty_contracts import (
    Availability,
    FactValue,
    Money,
    ValueType,
    decimal_to_string,
    parse_decimal_string,
)


def _fact(**overrides: object) -> FactValue:
    """Build a minimal available decimal fact, overriding single fields."""
    payload: dict[str, object] = {
        "key": "proceeds",
        "label": "Выручка",
        "value": "74586000",
        "value_type": ValueType.DECIMAL,
        "availability": Availability.AVAILABLE,
        "evidence_refs": ["ev-proceeds"],
    }
    payload.update(overrides)
    return FactValue.model_validate(payload)


def test_money_rejects_binary_float() -> None:
    """A float amount is refused rather than silently rounded."""
    with pytest.raises(ValidationError):
        Money(amount=2400000.00, currency="RUB")  # type: ignore[arg-type]


def test_money_serializes_as_plain_string() -> None:
    """The wire form keeps the exponent and uses no thousands separators."""
    money = Money(amount=Decimal("1920000.00"), currency="RUB")
    assert json.loads(money.model_dump_json())["amount"] == "1920000.00"
    assert str(money) == "1920000.00 RUB"


def test_money_round_trip_keeps_exact_decimal() -> None:
    """Serializing and parsing back does not go through float."""
    money = Money(amount=Decimal("0.10"), currency="RUB")
    assert Money.model_validate_json(money.model_dump_json()).amount == Decimal("0.10")


@pytest.mark.parametrize("raw", ["1 920 000", "1,920,000", "1.92e6", "", "-", "abc"])
def test_decimal_string_rejects_non_plain_forms(raw: str) -> None:
    """Separators, exponents and empty strings are not decimal wire forms."""
    with pytest.raises(ValueError, match="decimal string"):
        parse_decimal_string(raw)


def test_decimal_to_string_preserves_trailing_zeros() -> None:
    """Scale is information: it is not normalized away."""
    assert decimal_to_string(Decimal("355000.00")) == "355000.00"


def test_available_fact_requires_a_value() -> None:
    """Availability and payload cannot contradict each other."""
    with pytest.raises(ValidationError, match="must carry a value"):
        _fact(value=None)


def test_available_fact_requires_evidence() -> None:
    """A reported value without provenance is not publishable."""
    with pytest.raises(ValidationError, match="evidence ref"):
        _fact(evidence_refs=[])


def test_zero_is_an_available_value() -> None:
    """A reported zero is a real number, not an absence."""
    fact = _fact(value="0")
    assert fact.is_available
    assert not fact.is_unknown


@pytest.mark.parametrize(
    "availability",
    [
        Availability.MISSING,
        Availability.PRESENT_EMPTY,
        Availability.INVALID,
        Availability.RESTRICTED,
    ],
)
def test_non_available_states_carry_no_value(availability: Availability) -> None:
    """Missing, empty, invalid and restricted never smuggle a value through."""
    with pytest.raises(ValidationError, match="must not carry a value"):
        _fact(availability=availability)
    fact = _fact(availability=availability, value=None, evidence_refs=[])
    assert fact.value is None
    assert not fact.is_available


def test_missing_empty_and_invalid_stay_distinct() -> None:
    """The four non-values are different answers, not one ``None``."""
    states = {
        _fact(availability=state, value=None, evidence_refs=[]).availability
        for state in (
            Availability.MISSING,
            Availability.PRESENT_EMPTY,
            Availability.INVALID,
            Availability.RESTRICTED,
        )
    }
    assert len(states) == 4


def test_decimal_fact_rejects_a_float_payload() -> None:
    """A decimal fact travels as a string, never as a JSON number."""
    with pytest.raises(ValidationError):
        _fact(value=74586000.0)


def test_boolean_is_not_an_integer_fact() -> None:
    """``True`` does not satisfy an integer fact."""
    with pytest.raises(ValidationError, match="must not carry a boolean"):
        _fact(key="count", value=True, value_type=ValueType.INTEGER)


def test_integer_fact_accepts_an_integer() -> None:
    """An integer fact carries a real integer payload."""
    assert _fact(key="count", value=0, value_type=ValueType.INTEGER).value == 0


def test_date_fact_requires_a_real_calendar_day() -> None:
    """A display-layer date is a valid ``YYYY-MM-DD`` day."""
    _fact(key="issue_date", value="2025-01-31", value_type=ValueType.DATE)
    with pytest.raises(ValidationError):
        _fact(key="issue_date", value="31.01.2025", value_type=ValueType.DATE)


def test_currency_only_applies_to_decimal_facts() -> None:
    """A currency on a non-monetary type is a contract error."""
    with pytest.raises(ValidationError, match="currency applies only"):
        _fact(key="subject", value="поставка", value_type=ValueType.STRING, currency="RUB")


def test_enum_fact_keeps_an_unknown_raw_token() -> None:
    """An unrecognized external token parses and is not rewritten."""
    fact = _fact(key="zsk_risk_level", value="PURPLE", value_type=ValueType.ENUM)
    assert fact.value == "PURPLE"
