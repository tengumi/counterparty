"""Availability semantics: missing, zero, empty, invalid and restricted."""

from decimal import Decimal

import pytest

from counterparty_domain import (
    UNKNOWN_AVAILABILITY,
    Availability,
    FactSlot,
    UnavailableValueError,
    first_available,
)


def test_zero_is_an_available_value() -> None:
    """A real zero is data, not a non-value."""
    slot = FactSlot[Decimal].available(Decimal("0"))
    assert slot.is_available
    assert slot.unwrap() == 0
    assert not slot.is_unknown


def test_missing_is_not_zero() -> None:
    """A missing number never turns into zero implicitly."""
    slot = FactSlot[Decimal].missing("field absent from snapshot")
    assert slot.value is None
    assert slot.is_unknown
    assert slot.value_or(Decimal("0")) == 0
    with pytest.raises(UnavailableValueError) as excinfo:
        slot.unwrap()
    assert excinfo.value.availability == Availability.MISSING.value
    assert excinfo.value.reason == "field absent from snapshot"


def test_present_empty_only_proves_absence_when_confirmed() -> None:
    """An empty object is not automatically a confirmed ``count = 0``."""
    unconfirmed = FactSlot[int].present_empty("empty aggregate object")
    confirmed = FactSlot[int].present_empty("no records", confirms_absence=True)
    assert not unconfirmed.is_evidence_of_absence
    assert confirmed.is_evidence_of_absence
    assert not unconfirmed.is_unknown


def test_unknown_states_cover_missing_invalid_and_restricted() -> None:
    """Absence of data is never treated as absence of risk."""
    assert {
        Availability.MISSING,
        Availability.INVALID,
        Availability.RESTRICTED,
    } == UNKNOWN_AVAILABILITY
    assert FactSlot[str].invalid("malformed").is_unknown
    assert FactSlot[str].restricted("tenant scope").is_unknown


def test_slot_invariants_are_enforced() -> None:
    """A slot cannot claim availability without a value, or vice versa."""
    with pytest.raises(ValueError, match="must carry a value"):
        FactSlot[int](value=None, availability=Availability.AVAILABLE)
    with pytest.raises(ValueError, match="must not carry a value"):
        FactSlot[int](value=1, availability=Availability.MISSING)
    with pytest.raises(ValueError, match="confirms_absence"):
        FactSlot[int](value=None, availability=Availability.MISSING, confirms_absence=True)


def test_map_preserves_non_available_state() -> None:
    """Transformations never resurrect a value that was not there."""
    assert FactSlot[int].available(2).map(str).unwrap() == "2"
    mapped = FactSlot[int].invalid("bad").map(str)
    assert mapped.availability is Availability.INVALID
    assert mapped.value is None


def test_evidence_and_warnings_accumulate_without_duplicates() -> None:
    """Attaching the same evidence twice does not duplicate the reference."""
    slot = FactSlot[int].available(1).with_evidence("ev-1", "ev-1", "ev-2")
    assert slot.evidence_refs == ("ev-1", "ev-2")
    assert slot.with_warning("check period").warnings == ("check period",)


def test_first_available_prefers_data_over_non_values() -> None:
    """The first trustworthy value wins; otherwise the first reason survives."""
    missing = FactSlot[int].missing("absent")
    present = FactSlot[int].available(7)
    assert first_available([missing, present]).unwrap() == 7
    assert first_available([missing]).availability is Availability.MISSING
    assert first_available([]).availability is Availability.MISSING
