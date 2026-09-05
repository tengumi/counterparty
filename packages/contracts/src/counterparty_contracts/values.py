"""Scalar value conventions shared by every public contract.

Money is a :class:`~decimal.Decimal` and never a binary float, so an amount
survives the round trip through JSON unchanged. On the wire a decimal is a
plain string without thousands separators or exponent (``"1920000.00"``), as
required by the serialization rules of the contract.

Source ``$date`` values stay exact instants (:data:`UtcDatetime`). The source
encodes local midnights at more than one UTC offset, so narrowing one to a
calendar date requires guessing a timezone and can move the day. A calendar
date (:data:`CalendarDate`) is therefore a display-layer value only, produced
where the applied timezone is known.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer, StringConstraints

from .base import ContractModel

__all__ = [
    "MAX_FISCAL_YEAR",
    "MIN_FISCAL_YEAR",
    "CalendarDate",
    "CurrencyCode",
    "DecimalString",
    "FiscalYear",
    "Money",
    "NonNegativeCount",
    "Percent",
    "decimal_to_string",
    "parse_calendar_date",
    "parse_decimal_string",
]

MIN_FISCAL_YEAR = 1900
MAX_FISCAL_YEAR = 2200

DECIMAL_STRING_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
"""Accepted wire form of a decimal: no separators, no exponent, no bare dot."""

_CALENDAR_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _no_binary_float(value: object) -> object:
    """Reject ``float`` input before it can silently lose monetary precision."""
    if isinstance(value, float):
        raise ValueError("decimal values must not be transported as float")
    return value


def _finite_decimal(value: Decimal) -> Decimal:
    """Reject ``NaN`` and infinities, which are not reportable amounts."""
    if not value.is_finite():
        raise ValueError("decimal value must be finite")
    return value


def decimal_to_string(value: Decimal) -> str:
    """Render a decimal in the plain wire form, preserving its exponent."""
    return format(value, "f")


DecimalString = Annotated[
    Decimal,
    BeforeValidator(_no_binary_float),
    AfterValidator(_finite_decimal),
    PlainSerializer(decimal_to_string, return_type=str, when_used="json"),
]
"""A decimal accepted from a string or a ``Decimal`` and emitted as a string."""


def parse_decimal_string(raw: str) -> Decimal:
    """Parse the wire form of a decimal.

    Args:
        raw: Candidate string such as ``"-300000"`` or ``"1920000.00"``.

    Returns:
        The parsed decimal.

    Raises:
        ValueError: If the string is not the plain decimal wire form.
    """
    if DECIMAL_STRING_PATTERN.fullmatch(raw) is None:
        raise ValueError("decimal string must be plain digits with an optional single dot")
    try:
        return Decimal(raw)
    except InvalidOperation as error:  # pragma: no cover - guarded by the pattern
        raise ValueError("decimal string is not a number") from error


def parse_calendar_date(raw: str) -> date:
    """Parse a display-layer ``YYYY-MM-DD`` day.

    Args:
        raw: Candidate string such as ``"2025-12-31"``.

    Returns:
        The parsed calendar day.

    Raises:
        ValueError: If the string is not a real ``YYYY-MM-DD`` day.
    """
    if _CALENDAR_DATE_PATTERN.fullmatch(raw) is None:
        raise ValueError("calendar date must be formatted YYYY-MM-DD")
    return date.fromisoformat(raw)


def _valid_calendar_date(value: str) -> str:
    """Accept only a real ``YYYY-MM-DD`` day."""
    parse_calendar_date(value)
    return value


CalendarDate = Annotated[str, AfterValidator(_valid_calendar_date)]
"""A display-layer calendar day; never a substitute for a source instant."""

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
"""ISO 4217 alphabetic code. ``RUB`` for report figures is a documented
interpretation of the fixture, not a field the source provides."""

FiscalYear = Annotated[int, Field(ge=MIN_FISCAL_YEAR, le=MAX_FISCAL_YEAR)]
"""A reporting year. The snapshot date is a different thing and never
substitutes for it."""

NonNegativeCount = Annotated[int, Field(ge=0)]
"""A counted number of records. Zero counted records is a real value; an
unknown count is expressed by availability, not by ``0``."""

Percent = Annotated[Decimal, BeforeValidator(_no_binary_float), Field(ge=0, le=100)]
"""A percentage in ``0..100``; the advance share is validated against it."""


class Money(ContractModel):
    """An amount together with the currency it is denominated in."""

    amount: DecimalString
    currency: CurrencyCode

    def __str__(self) -> str:
        """Render the amount and its currency for logs and messages."""
        return f"{decimal_to_string(self.amount)} {self.currency}"
