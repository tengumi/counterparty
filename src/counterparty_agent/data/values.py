"""Безопасные преобразования скалярных значений и enum."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from counterparty_agent.data.errors import SnapshotSourceError
from counterparty_agent.models import (
    SourceOutcome,
)


def _mapping(value: object, field_path: str, record_number: int) -> Mapping[str, Any]:
    if isinstance(value, dict):
        return cast(Mapping[str, Any], value)
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть объектом",
    )


def _optional_mapping(
    parent: Mapping[str, Any],
    key: str,
    field_path: str,
    record_number: int,
) -> Mapping[str, Any] | None:
    if key not in parent:
        return None
    return _mapping(parent[key], field_path, record_number)


def _sequence(value: object, field_path: str, record_number: int) -> Sequence[object]:
    if isinstance(value, list):
        return cast(Sequence[object], value)
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть массивом",
    )


def _required_string(value: object, field_path: str, record_number: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть непустой строкой",
    )


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_int(value: object, field_path: str, record_number: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть целым числом",
    )


def _optional_int(
    parent: Mapping[str, Any],
    key: str,
    field_path: str,
    record_number: int,
) -> int | None:
    if key not in parent:
        return None
    return _required_int(parent[key], field_path, record_number)


def _required_bool(value: object, field_path: str, record_number: int) -> bool:
    if isinstance(value, bool):
        return value
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть логическим значением",
    )


def _required_decimal(value: object, field_path: str, record_number: int) -> Decimal:
    if isinstance(value, bool):
        raise _record_error(
            "invalid_field_type",
            f"Поле {field_path} записи {record_number} должно быть числом",
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            pass
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно быть числом",
    )


def _optional_decimal(
    parent: Mapping[str, Any],
    key: str,
    field_path: str,
    record_number: int,
) -> Decimal | None:
    if key not in parent:
        return None
    return _required_decimal(parent[key], field_path, record_number)


def _optional_decimal_from_mapping(
    parent: Mapping[str, Any] | None,
    key: str,
    field_path: str,
    record_number: int,
) -> Decimal | None:
    if parent is None:
        return None
    return _optional_decimal(parent, key, field_path, record_number)


def _required_datetime(value: object, field_path: str, record_number: int) -> datetime:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value
    raise _record_error(
        "invalid_field_type",
        f"Поле {field_path} записи {record_number} должно содержать дату с часовым поясом",
    )


def _optional_datetime(
    parent: Mapping[str, Any],
    key: str,
    field_path: str,
    record_number: int,
) -> datetime | None:
    if key not in parent:
        return None
    return _required_datetime(parent[key], field_path, record_number)


def _stable_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _record_error(code: str, message: str) -> SnapshotSourceError:
    return SnapshotSourceError(SourceOutcome.INVALID, code, message)
