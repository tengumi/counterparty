"""Format and checksum validation of registry identifiers."""

import pytest

from counterparty_domain import (
    IdentifierError,
    IdentifierKind,
    IdentifierProblem,
    inn_check_digits,
    inn_slot,
    ogrn_slot,
    parse_inn,
    parse_ogrn,
    validate_inn,
    validate_kpp,
    validate_ogrn,
)
from counterparty_domain.facts import Availability


def test_fixture_inn_from_specs_is_valid() -> None:
    """The documented fixture INN passes the 10-digit checksum."""
    validation = validate_inn("7449088645")
    assert validation.is_valid
    assert validation.kind is IdentifierKind.LEGAL_ENTITY
    assert validation.normalized == "7449088645"


@pytest.mark.parametrize("inn", ["7707083893", "5027089703", "0123456788"])
def test_valid_ten_digit_inn(inn: str) -> None:
    """Known-good 10-digit values validate, leading zeros preserved."""
    assert validate_inn(inn).is_valid


@pytest.mark.parametrize("inn", ["500100732259", "760307073214", "012345678943"])
def test_valid_twelve_digit_inn(inn: str) -> None:
    """Individual INNs validate against both control digits."""
    validation = validate_inn(inn)
    assert validation.is_valid
    assert validation.kind is IdentifierKind.INDIVIDUAL


def test_ten_digit_checksum_mismatch() -> None:
    """A single altered control digit is rejected, not normalized away."""
    validation = validate_inn("7449088644")
    assert not validation.is_valid
    assert IdentifierProblem.CHECKSUM_MISMATCH in validation.problems
    assert validation.normalized is None


def test_twelve_digit_second_control_digit_mismatch() -> None:
    """The eleventh digit alone is not enough; the twelfth is checked too."""
    digits = [int(character) for character in "500100732259"]
    eleventh, twelfth = inn_check_digits(digits)
    assert (digits[10], digits[11]) == (eleventh, twelfth)
    broken = "50010073225" + str((twelfth + 1) % 10)
    assert IdentifierProblem.CHECKSUM_MISMATCH in validate_inn(broken).problems


def test_eleven_digit_inn_is_bad_length() -> None:
    """Only 10 and 12 digits exist; 11 is a length problem, not a checksum."""
    validation = validate_inn("74490886451")
    assert validation.problems == (IdentifierProblem.BAD_LENGTH,)


def test_non_digit_inn() -> None:
    """Letters are rejected before any arithmetic is attempted."""
    assert validate_inn("74490886X5").problems == (IdentifierProblem.NOT_DIGITS,)


def test_all_zero_inn_is_rejected_even_though_checksum_holds() -> None:
    """An all-zero INN satisfies the arithmetic but is not a real identifier."""
    validation = validate_inn("0000000000")
    assert IdentifierProblem.ALL_ZEROS in validation.problems
    assert IdentifierProblem.CHECKSUM_MISMATCH not in validation.problems


def test_inn_check_digits_rejects_other_lengths() -> None:
    """The checksum helper refuses inputs it has no algorithm for."""
    with pytest.raises(ValueError, match="10 or 12"):
        inn_check_digits([1, 2, 3])


def test_missing_and_empty_inn_are_distinct() -> None:
    """``None`` is absent; an empty string was supplied and is empty."""
    absent = validate_inn(None)
    empty = validate_inn("   ")
    assert absent.is_absent and not absent.is_empty
    assert empty.is_empty and not empty.is_absent


def test_inn_slot_maps_states_onto_availability() -> None:
    """The slot form keeps missing, empty and invalid apart."""
    assert inn_slot("7449088645").availability is Availability.AVAILABLE
    assert inn_slot(None).availability is Availability.MISSING
    assert inn_slot("").availability is Availability.PRESENT_EMPTY
    assert inn_slot("7449088644").availability is Availability.INVALID
    assert inn_slot(7449088645).availability is Availability.INVALID


def test_parse_inn_raises_with_problem_codes() -> None:
    """The strict boundary reports machine-readable problems."""
    with pytest.raises(IdentifierError) as excinfo:
        parse_inn("7449088644")
    assert IdentifierProblem.CHECKSUM_MISMATCH.value in excinfo.value.problems
    assert parse_inn(" 7449088645 ") == "7449088645"


@pytest.mark.parametrize("ogrn", ["1027700132195", "1234567890127"])
def test_valid_thirteen_digit_ogrn(ogrn: str) -> None:
    """A 13-digit OGRN validates modulo 11."""
    validation = validate_ogrn(ogrn)
    assert validation.is_valid
    assert validation.kind is IdentifierKind.LEGAL_ENTITY


def test_valid_fifteen_digit_ogrnip() -> None:
    """A 15-digit OGRNIP validates modulo 13."""
    validation = validate_ogrn("304500116000157")
    assert validation.is_valid
    assert validation.kind is IdentifierKind.INDIVIDUAL


def test_ogrn_checksum_mismatch() -> None:
    """A wrong final digit is a checksum problem."""
    assert IdentifierProblem.CHECKSUM_MISMATCH in validate_ogrn("1027700132194").problems


def test_ogrn_bad_prefix() -> None:
    """The record attribute digit is constrained per identifier length."""
    problems = validate_ogrn("9027700132195").problems
    assert IdentifierProblem.BAD_PREFIX in problems


def test_ogrn_bad_length_and_slot() -> None:
    """A 14-digit value belongs to neither register."""
    assert validate_ogrn("10277001321950").problems == (IdentifierProblem.BAD_LENGTH,)
    assert ogrn_slot("10277001321950").availability is Availability.INVALID
    assert ogrn_slot(None).availability is Availability.MISSING


def test_parse_ogrn_returns_normalized_value() -> None:
    """Surrounding whitespace is trimmed, digits are preserved."""
    assert parse_ogrn(" 1027700132195 ") == "1027700132195"


def test_kpp_shape() -> None:
    """A KPP has no checksum, only a fixed shape with a letter-capable code."""
    assert validate_kpp("770101001").is_valid
    assert validate_kpp("7701AB001").is_valid
    assert validate_kpp("77010100").problems == (IdentifierProblem.BAD_LENGTH,)
    assert IdentifierProblem.BAD_ALPHABET in validate_kpp("7701ab001").problems
