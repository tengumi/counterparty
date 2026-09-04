"""Распаковка JSON-обёрток и контроль структуры."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from counterparty_agent.data.errors import SnapshotSourceError
from counterparty_agent.models import (
    SourceOutcome,
)


def decode_extended_json(value: object) -> object:
    """Рекурсивно распаковать поддерживаемые значения Mongo Extended JSON."""

    if isinstance(value, list):
        return [decode_extended_json(item) for item in value]
    if not isinstance(value, dict):
        return value

    if set(value) == {"$date"}:
        return _decode_date(value["$date"])
    if set(value) == {"$numberLong"}:
        number = value["$numberLong"]
        if not isinstance(number, str):
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_number_long",
                "Поле $numberLong должно содержать строку",
            )
        try:
            return int(number)
        except ValueError as error:
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_number_long",
                "Поле $numberLong содержит некорректное целое число",
            ) from error
    if set(value) == {"$numberDecimal"}:
        number = value["$numberDecimal"]
        if not isinstance(number, str):
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_number_decimal",
                "Поле $numberDecimal должно содержать строку",
            )
        try:
            return Decimal(number)
        except (InvalidOperation, ValueError) as error:
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_number_decimal",
                "Поле $numberDecimal содержит некорректное число",
            ) from error
    if set(value) == {"$oid"} and isinstance(value["$oid"], str):
        return value["$oid"]
    return {str(key): decode_extended_json(item) for key, item in value.items()}


def _decode_date(value: object) -> datetime:
    if isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise SnapshotSourceError(
                SourceOutcome.INVALID,
                "invalid_date",
                "Поле $date содержит некорректную дату",
            ) from error
        return result if result.tzinfo is not None else result.replace(tzinfo=UTC)
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    raise SnapshotSourceError(
        SourceOutcome.INVALID,
        "invalid_date",
        "Поле $date имеет неподдерживаемый тип",
    )
