"""Validation of Russian registry identifiers: INN, OGRN, OGRNIP and KPP.

Identifiers stay strings: leading zeros are significant and arithmetic on them
is never meaningful. Validation reports structured problems instead of
throwing, because import must record a mismatch rather than silently drop a
record; ``parse_*`` wrappers exist for boundaries that must reject bad input.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .errors import IdentifierError
from .facts import FactSlot

__all__ = [
    "IdentifierKind",
    "IdentifierProblem",
    "IdentifierValidation",
    "inn_check_digits",
    "inn_slot",
    "ogrn_slot",
    "parse_inn",
    "parse_kpp",
    "parse_ogrn",
    "validate_inn",
    "validate_kpp",
    "validate_ogrn",
]

_INN_10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_12_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN_12_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)

# First digit of an OGRN/OGRNIP: registry attribute of the record.
_OGRN_PREFIXES = frozenset("1235")
_OGRNIP_PREFIXES = frozenset("34")
_KPP_REASON_ALPHABET = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class IdentifierKind(StrEnum):
    """Which registry subject an identifier belongs to."""

    LEGAL_ENTITY = "legal_entity"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


class IdentifierProblem(StrEnum):
    """Machine-readable reasons an identifier was rejected."""

    NOT_PROVIDED = "not_provided"
    EMPTY = "empty"
    NOT_A_STRING = "not_a_string"
    CONTAINS_WHITESPACE = "contains_whitespace"
    NOT_DIGITS = "not_digits"
    BAD_LENGTH = "bad_length"
    ALL_ZEROS = "all_zeros"
    BAD_PREFIX = "bad_prefix"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    BAD_ALPHABET = "bad_alphabet"


@dataclass(frozen=True, slots=True)
class IdentifierValidation:
    """Outcome of validating one identifier."""

    raw: str | None
    normalized: str | None
    kind: IdentifierKind
    problems: tuple[IdentifierProblem, ...]

    @property
    def is_valid(self) -> bool:
        """Whether the identifier passed format and checksum validation."""
        return not self.problems and self.normalized is not None

    @property
    def is_absent(self) -> bool:
        """Whether nothing was supplied at all, as opposed to a bad value."""
        return IdentifierProblem.NOT_PROVIDED in self.problems

    @property
    def is_empty(self) -> bool:
        """Whether an empty string was supplied, which is not the same as absent."""
        return IdentifierProblem.EMPTY in self.problems

    def require(self) -> str:
        """Return the normalized identifier or raise.

        Raises:
            IdentifierError: If validation found any problem.
        """
        if self.normalized is None or self.problems:
            raise IdentifierError(
                f"invalid identifier {self.raw!r}",
                raw=self.raw,
                problems=[problem.value for problem in self.problems],
            )
        return self.normalized


def _normalize(raw: object) -> tuple[str | None, list[IdentifierProblem]]:
    """Trim a candidate identifier and report structural problems."""
    problems: list[IdentifierProblem] = []
    if raw is None:
        return None, [IdentifierProblem.NOT_PROVIDED]
    if not isinstance(raw, str):
        return None, [IdentifierProblem.NOT_A_STRING]
    trimmed = raw.strip()
    if not trimmed:
        return None, [IdentifierProblem.EMPTY]
    if any(character.isspace() for character in trimmed):
        problems.append(IdentifierProblem.CONTAINS_WHITESPACE)
    return trimmed, problems


def _weighted_check_digit(digits: Sequence[int], weights: Sequence[int]) -> int:
    """Return the classic ``sum(w*d) % 11 % 10`` control digit."""
    return sum(weight * digit for weight, digit in zip(weights, digits, strict=True)) % 11 % 10


def inn_check_digits(digits: Sequence[int]) -> tuple[int, ...]:
    """Return the expected control digits for a 10- or 12-digit INN body.

    Args:
        digits: The full INN as digits; only the leading body is used.

    Returns:
        One control digit for a 10-digit INN, two for a 12-digit INN.

    Raises:
        ValueError: If the length is neither 10 nor 12.
    """
    if len(digits) == 10:
        return (_weighted_check_digit(digits[:9], _INN_10_WEIGHTS),)
    if len(digits) == 12:
        return (
            _weighted_check_digit(digits[:10], _INN_12_WEIGHTS_11),
            _weighted_check_digit(digits[:11], _INN_12_WEIGHTS_12),
        )
    raise ValueError("INN must contain 10 or 12 digits")


def validate_inn(raw: object) -> IdentifierValidation:
    """Validate an INN's length, alphabet and control digits.

    A 10-digit INN belongs to a legal entity, a 12-digit one to an individual
    or sole proprietor.
    """
    normalized, problems = _normalize(raw)
    if normalized is None:
        return IdentifierValidation(
            raw=raw if isinstance(raw, str) else None,
            normalized=None,
            kind=IdentifierKind.UNKNOWN,
            problems=tuple(problems),
        )

    kind = IdentifierKind.UNKNOWN
    if not normalized.isdecimal() or not normalized.isascii():
        problems.append(IdentifierProblem.NOT_DIGITS)
    elif len(normalized) not in (10, 12):
        problems.append(IdentifierProblem.BAD_LENGTH)
    else:
        kind = IdentifierKind.LEGAL_ENTITY if len(normalized) == 10 else IdentifierKind.INDIVIDUAL
        digits = [int(character) for character in normalized]
        if set(digits) == {0}:
            problems.append(IdentifierProblem.ALL_ZEROS)
        expected = inn_check_digits(digits)
        if tuple(digits[-len(expected) :]) != expected:
            problems.append(IdentifierProblem.CHECKSUM_MISMATCH)

    return IdentifierValidation(
        raw=normalized,
        normalized=normalized if not problems else None,
        kind=kind,
        problems=tuple(problems),
    )


def validate_ogrn(raw: object) -> IdentifierValidation:
    """Validate a 13-digit OGRN or a 15-digit OGRNIP, including its checksum.

    The control digit is the remainder of the leading body divided by 11
    (OGRN) or 13 (OGRNIP), taken modulo 10.
    """
    normalized, problems = _normalize(raw)
    if normalized is None:
        return IdentifierValidation(
            raw=raw if isinstance(raw, str) else None,
            normalized=None,
            kind=IdentifierKind.UNKNOWN,
            problems=tuple(problems),
        )

    kind = IdentifierKind.UNKNOWN
    if not normalized.isdecimal() or not normalized.isascii():
        problems.append(IdentifierProblem.NOT_DIGITS)
    elif len(normalized) not in (13, 15):
        problems.append(IdentifierProblem.BAD_LENGTH)
    else:
        is_ogrnip = len(normalized) == 15
        kind = IdentifierKind.INDIVIDUAL if is_ogrnip else IdentifierKind.LEGAL_ENTITY
        allowed = _OGRNIP_PREFIXES if is_ogrnip else _OGRN_PREFIXES
        if normalized[0] not in allowed:
            problems.append(IdentifierProblem.BAD_PREFIX)
        divisor = 13 if is_ogrnip else 11
        if int(normalized[:-1]) % divisor % 10 != int(normalized[-1]):
            problems.append(IdentifierProblem.CHECKSUM_MISMATCH)

    return IdentifierValidation(
        raw=normalized,
        normalized=normalized if not problems else None,
        kind=kind,
        problems=tuple(problems),
    )


def validate_kpp(raw: object) -> IdentifierValidation:
    """Validate a 9-character KPP: ``NNNN`` + reason code + ``NNN``.

    The reason code allows uppercase Latin letters, so the KPP has no
    checksum; only shape is verified.
    """
    normalized, problems = _normalize(raw)
    if normalized is None:
        return IdentifierValidation(
            raw=raw if isinstance(raw, str) else None,
            normalized=None,
            kind=IdentifierKind.UNKNOWN,
            problems=tuple(problems),
        )

    if len(normalized) != 9:
        problems.append(IdentifierProblem.BAD_LENGTH)
    else:
        head, reason, tail = normalized[:4], normalized[4:6], normalized[6:]
        if not (head.isdecimal() and head.isascii() and tail.isdecimal() and tail.isascii()):
            problems.append(IdentifierProblem.NOT_DIGITS)
        if any(character not in _KPP_REASON_ALPHABET for character in reason):
            problems.append(IdentifierProblem.BAD_ALPHABET)

    return IdentifierValidation(
        raw=normalized,
        normalized=normalized if not problems else None,
        kind=IdentifierKind.LEGAL_ENTITY if not problems else IdentifierKind.UNKNOWN,
        problems=tuple(problems),
    )


def _slot(validation: IdentifierValidation, label: str) -> FactSlot[str]:
    """Map a validation outcome onto the shared availability semantics."""
    if validation.is_valid and validation.normalized is not None:
        return FactSlot[str].available(validation.normalized)
    if validation.is_absent:
        return FactSlot[str].missing(f"{label} was not provided")
    if validation.is_empty:
        return FactSlot[str].present_empty(f"{label} was provided as an empty string")
    return FactSlot[str].invalid(
        f"{label} failed validation: {', '.join(problem.value for problem in validation.problems)}"
    )


def inn_slot(raw: object) -> FactSlot[str]:
    """Validate an INN and express the outcome as a ``FactSlot``."""
    return _slot(validate_inn(raw), "INN")


def ogrn_slot(raw: object) -> FactSlot[str]:
    """Validate an OGRN/OGRNIP and express the outcome as a ``FactSlot``."""
    return _slot(validate_ogrn(raw), "OGRN")


def parse_inn(raw: object) -> str:
    """Return a valid normalized INN or raise ``IdentifierError``."""
    return validate_inn(raw).require()


def parse_ogrn(raw: object) -> str:
    """Return a valid normalized OGRN/OGRNIP or raise ``IdentifierError``."""
    return validate_ogrn(raw).require()


def parse_kpp(raw: object) -> str:
    """Return a valid normalized KPP or raise ``IdentifierError``."""
    return validate_kpp(raw).require()
