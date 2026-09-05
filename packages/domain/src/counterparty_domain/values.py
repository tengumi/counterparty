"""Decimal, integer and calendar-date helpers for report values.

Money is never parsed into ``float``: the contract transports decimals as
plain strings such as ``"1920000.00"``. A malformed number stays unavailable
with a warning; it never degrades into ``0``.
"""

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext

from .facts import FactSlot

__all__ = [
    "MAX_FISCAL_YEAR",
    "MIN_FISCAL_YEAR",
    "MONEY_EXPONENT",
    "format_decimal",
    "is_zero",
    "parse_date",
    "parse_decimal",
    "parse_fiscal_year",
    "parse_integer",
    "quantize_money",
    "sum_decimals",
]

MONEY_EXPONENT = Decimal("0.01")
MIN_FISCAL_YEAR = 1900
MAX_FISCAL_YEAR = 2200

_DECIMAL_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
_INTEGER_PATTERN = re.compile(r"[+-]?\d+")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_decimal(raw: object, *, label: str = "value") -> FactSlot[Decimal]:
    """Parse a report number into ``Decimal`` with explicit availability.

    ``None`` is missing, an empty string is present-but-empty, and anything
    unparseable is invalid. ``float`` input is rejected: binary floats are
    forbidden for monetary values.
    """
    if raw is None:
        return FactSlot[Decimal].missing(f"{label} was not provided")
    if isinstance(raw, bool):
        return FactSlot[Decimal].invalid(f"{label} is a boolean, not a number")
    if isinstance(raw, Decimal):
        if not raw.is_finite():
            return FactSlot[Decimal].invalid(f"{label} is not a finite decimal")
        return FactSlot[Decimal].available(raw)
    if isinstance(raw, int):
        return FactSlot[Decimal].available(Decimal(raw))
    if isinstance(raw, float):
        return FactSlot[Decimal].invalid(f"{label} arrived as float, which is unsafe for money")
    if not isinstance(raw, str):
        return FactSlot[Decimal].invalid(f"{label} has unsupported type {type(raw).__name__}")

    trimmed = raw.strip()
    if not trimmed:
        return FactSlot[Decimal].present_empty(f"{label} was provided as an empty string")
    if _DECIMAL_PATTERN.fullmatch(trimmed) is None:
        return FactSlot[Decimal].invalid(f"{label} is not a plain decimal string: {trimmed!r}")
    try:
        parsed = Decimal(trimmed)
    except DecimalException:  # pragma: no cover - guarded by the pattern above
        return FactSlot[Decimal].invalid(f"{label} could not be parsed as a decimal")
    return FactSlot[Decimal].available(parsed)


def parse_integer(raw: object, *, label: str = "value") -> FactSlot[int]:
    """Parse a whole number, keeping missing, empty and invalid distinct."""
    if raw is None:
        return FactSlot[int].missing(f"{label} was not provided")
    if isinstance(raw, bool):
        return FactSlot[int].invalid(f"{label} is a boolean, not an integer")
    if isinstance(raw, int):
        return FactSlot[int].available(raw)
    if isinstance(raw, Decimal):
        if raw.is_finite() and raw == raw.to_integral_value():
            return FactSlot[int].available(int(raw))
        return FactSlot[int].invalid(f"{label} is not a whole number")
    if not isinstance(raw, str):
        return FactSlot[int].invalid(f"{label} has unsupported type {type(raw).__name__}")

    trimmed = raw.strip()
    if not trimmed:
        return FactSlot[int].present_empty(f"{label} was provided as an empty string")
    if _INTEGER_PATTERN.fullmatch(trimmed) is None:
        return FactSlot[int].invalid(f"{label} is not an integer string: {trimmed!r}")
    return FactSlot[int].available(int(trimmed))


def parse_date(raw: object, *, label: str = "date") -> FactSlot[date]:
    """Parse a calendar date in ``YYYY-MM-DD`` form.

    A ``datetime`` is accepted and truncated with a warning, because a
    calendar date carries no time zone and must not silently shift a day.
    """
    if raw is None:
        return FactSlot[date].missing(f"{label} was not provided")
    if isinstance(raw, datetime):
        return (
            FactSlot[date]
            .available(raw.date())
            .with_warning(f"{label} arrived as a timestamp and was truncated to its calendar date")
        )
    if isinstance(raw, date):
        return FactSlot[date].available(raw)
    if not isinstance(raw, str):
        return FactSlot[date].invalid(f"{label} has unsupported type {type(raw).__name__}")

    trimmed = raw.strip()
    if not trimmed:
        return FactSlot[date].present_empty(f"{label} was provided as an empty string")
    if _DATE_PATTERN.fullmatch(trimmed) is None:
        return FactSlot[date].invalid(f"{label} is not an ISO calendar date: {trimmed!r}")
    try:
        parsed = date.fromisoformat(trimmed)
    except ValueError:
        return FactSlot[date].invalid(f"{label} is not a real calendar date: {trimmed!r}")
    return FactSlot[date].available(parsed)


def parse_fiscal_year(raw: object, *, label: str = "fiscal year") -> FactSlot[int]:
    """Parse a financial year, which is an integer and never a report date."""
    slot = parse_integer(raw, label=label)
    if not slot.is_available:
        return slot
    year = slot.unwrap()
    if not MIN_FISCAL_YEAR <= year <= MAX_FISCAL_YEAR:
        return FactSlot[int].invalid(
            f"{label} {year} is outside {MIN_FISCAL_YEAR}..{MAX_FISCAL_YEAR}"
        )
    return slot


def quantize_money(value: Decimal, *, exponent: Decimal = MONEY_EXPONENT) -> Decimal:
    """Round a monetary amount half-up to the given exponent."""
    with localcontext() as context:
        context.prec = 34
        return value.quantize(exponent, rounding="ROUND_HALF_UP")


def format_decimal(value: Decimal) -> str:
    """Render a decimal in the wire form: plain digits, no exponent."""
    return f"{value:f}"


def is_zero(slot: FactSlot[Decimal] | FactSlot[int]) -> bool:
    """Whether the slot holds an actual zero, as opposed to a non-value.

    Missing, empty, invalid and restricted slots are never zero.
    """
    return slot.is_available and slot.unwrap() == 0


def sum_decimals(
    slots: Iterable[FactSlot[Decimal]],
    *,
    label: str = "total",
    evidence_refs: Sequence[str] = (),
) -> FactSlot[Decimal]:
    """Sum decimals, refusing to treat an unknown part as zero.

    Empty input yields ``present_empty`` rather than ``0``: nothing was summed,
    which is not the same as a confirmed zero total.
    """
    total = Decimal(0)
    counted = 0
    collected: list[str] = list(evidence_refs)
    for slot in slots:
        if not slot.is_available:
            return FactSlot[Decimal].missing(
                f"{label} is unknown: a component is {slot.availability.value}",
                evidence_refs=collected,
            )
        total += slot.unwrap()
        counted += 1
        collected.extend(ref for ref in slot.evidence_refs if ref not in collected)
    if counted == 0:
        return FactSlot[Decimal].present_empty(
            f"{label} had no components to sum", evidence_refs=collected
        )
    return FactSlot[Decimal].available(total, evidence_refs=collected)
