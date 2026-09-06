"""Decoding of the MongoDB Extended JSON used by the provided snapshot.

The source file is a Mongo export, so values arrive wrapped: ``{"$date": ...}``
and ``{"$numberLong": ...}`` are the two wrappers the approved file actually
uses. Decoding them here rather than in each caller keeps three guarantees:

* identity and precision survive — ``$numberLong`` becomes an exact ``int`` and
  a JSON fraction becomes ``Decimal``; ``float`` is never produced;
* an unrecognized wrapper or an unparsable value becomes :class:`Invalid` with
  a warning, never ``0``, ``None`` or a silently dropped field;
* an absent key, an explicit ``null``, an empty container, a reported zero and
  an unparsable value stay four different observations. :class:`FieldProbe` and
  :class:`SectionProbe` are the only supported way to ask which one occurred.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Self

from counterparty_storage.reports import SourceState

__all__ = [
    "MISSING",
    "DecodeIssue",
    "Decoded",
    "FieldProbe",
    "Invalid",
    "IssueCode",
    "Missing",
    "SectionProbe",
    "decode",
    "json_pointer",
    "load_source_file",
    "probe_field",
    "probe_section",
]


class IssueCode(StrEnum):
    """Why one value could not be decoded as written."""

    UNKNOWN_WRAPPER = "unknown_wrapper"
    """A ``$``-prefixed object whose type this decoder does not implement."""

    MIXED_WRAPPER_OBJECT = "mixed_wrapper_object"
    """An object mixing ``$``-keys with ordinary keys; the shape is ambiguous."""

    MALFORMED_DATE = "malformed_date"
    MALFORMED_NUMBER = "malformed_number"
    UNSUPPORTED_FLOAT = "unsupported_float"
    """A binary float reached the decoder; money must never be a float."""


@dataclass(frozen=True, slots=True)
class DecodeIssue:
    """One decoding problem, addressed by the path it happened at."""

    code: IssueCode
    source_path: str
    detail: str


@dataclass(frozen=True, slots=True)
class Invalid:
    """A value that exists in the source but could not be decoded.

    The raw form is preserved so the import can store it for diagnosis instead
    of turning "unparsable" into "absent" or into a zero.
    """

    raw: object
    issue: DecodeIssue


class Missing:
    """Sentinel for a key that is absent from the source object.

    Distinct from ``None``, which means the source explicitly carried ``null``.
    """

    _instance: "Missing | None" = None

    def __new__(cls) -> Self:
        """Return the single shared sentinel instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance  # type: ignore[return-value]

    def __repr__(self) -> str:
        """Render as ``MISSING`` so a traceback names the state, not a class."""
        return "MISSING"

    def __bool__(self) -> bool:
        """Absence is falsy, but ``if value:`` must not be used to detect it."""
        return False


MISSING: Final = Missing()


@dataclass(frozen=True, slots=True)
class Decoded:
    """A decoded document together with everything that went wrong in it."""

    value: object
    issues: tuple[DecodeIssue, ...] = ()

    @property
    def is_clean(self) -> bool:
        """Whether the document decoded without a single issue."""
        return not self.issues


def json_pointer(*segments: str | int) -> str:
    """Build an RFC 6901 pointer, escaping ``~`` and ``/`` in key names."""
    parts = []
    for segment in segments:
        text = str(segment)
        parts.append(text.replace("~", "~0").replace("/", "~1"))
    return "".join(f"/{part}" for part in parts)


def _decode_date(raw: object, path: str, issues: list[DecodeIssue]) -> object:
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            issue = DecodeIssue(IssueCode.MALFORMED_DATE, path, f"unparsable $date {raw!r}")
            issues.append(issue)
            return Invalid({"$date": raw}, issue)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return datetime.fromtimestamp(raw / 1000, tz=UTC)
    issue = DecodeIssue(IssueCode.MALFORMED_DATE, path, f"unsupported $date payload {raw!r}")
    issues.append(issue)
    return Invalid({"$date": raw}, issue)


def _decode_integer(wrapper: str, raw: object, path: str, issues: list[DecodeIssue]) -> object:
    if isinstance(raw, bool):
        pass
    elif isinstance(raw, int):
        return raw
    elif isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            pass
    issue = DecodeIssue(IssueCode.MALFORMED_NUMBER, path, f"unparsable {wrapper} {raw!r}")
    issues.append(issue)
    return Invalid({wrapper: raw}, issue)


def _decode_decimal(raw: object, path: str, issues: list[DecodeIssue]) -> object:
    if isinstance(raw, str | int | Decimal) and not isinstance(raw, bool):
        try:
            return Decimal(raw)
        except InvalidOperation:
            pass
    issue = DecodeIssue(IssueCode.MALFORMED_NUMBER, path, f"unparsable $numberDecimal {raw!r}")
    issues.append(issue)
    return Invalid({"$numberDecimal": raw}, issue)


def _decode_wrapper(wrapper: str, raw: object, path: str, issues: list[DecodeIssue]) -> object:
    match wrapper:
        case "$date":
            return _decode_date(raw, path, issues)
        case "$numberLong" | "$numberInt":
            return _decode_integer(wrapper, raw, path, issues)
        case "$numberDecimal":
            return _decode_decimal(raw, path, issues)
        case "$oid":
            if isinstance(raw, str):
                return raw
    issue = DecodeIssue(
        IssueCode.UNKNOWN_WRAPPER,
        path,
        f"{wrapper} is not implemented; the value is kept unconverted",
    )
    issues.append(issue)
    return Invalid({wrapper: raw}, issue)


def _decode(value: object, path: str, issues: list[DecodeIssue]) -> object:
    if isinstance(value, Mapping):
        keys = list(value.keys())
        wrappers = [key for key in keys if isinstance(key, str) and key.startswith("$")]
        if wrappers and len(keys) == 1:
            return _decode_wrapper(wrappers[0], value[keys[0]], path, issues)
        if wrappers:
            issues.append(
                DecodeIssue(
                    IssueCode.MIXED_WRAPPER_OBJECT,
                    path,
                    f"object mixes wrapper keys {wrappers} with ordinary keys",
                )
            )
        return {
            str(key): _decode(item, path + json_pointer(str(key)), issues)
            for key, item in value.items()
        }
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return [
            _decode(item, path + json_pointer(index), issues) for index, item in enumerate(value)
        ]
    if isinstance(value, float):
        issue = DecodeIssue(
            IssueCode.UNSUPPORTED_FLOAT,
            path,
            "binary float reached the decoder; load the source with parse_float=Decimal",
        )
        issues.append(issue)
        return Invalid(value, issue)
    return value


def decode(document: object, *, base_path: str = "") -> Decoded:
    """Decode Extended JSON wrappers anywhere inside ``document``."""
    issues: list[DecodeIssue] = []
    value = _decode(document, base_path, issues)
    return Decoded(value=value, issues=tuple(issues))


def load_source_file(path: Path) -> list[Any]:
    """Read a source file, parsing fractions as ``Decimal`` instead of float.

    The approved snapshot is read in place; no cleaned or derived copy of it is
    written by this package.
    """
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle, parse_float=Decimal)
    if not isinstance(loaded, list):
        raise ValueError(f"expected a JSON array of records, got {type(loaded).__name__}")
    return loaded


def _state_of(value: object) -> SourceState:
    if isinstance(value, Missing):
        return SourceState.MISSING
    if isinstance(value, Invalid):
        return SourceState.INVALID
    if value is None:
        return SourceState.PRESENT_EMPTY
    if isinstance(value, str | list | dict | tuple) and len(value) == 0:
        return SourceState.PRESENT_EMPTY
    return SourceState.PRESENT


@dataclass(frozen=True, slots=True)
class FieldProbe:
    """What was actually found at one field of a decoded document."""

    source_path: str
    state: SourceState
    value: object = MISSING
    issue: DecodeIssue | None = None

    @property
    def is_present(self) -> bool:
        """Whether a usable value was found. A reported zero counts as present."""
        return self.state is SourceState.PRESENT

    def as_value(self) -> object | None:
        """Return the value, or ``None`` for anything that is not present.

        ``None`` here means "no trustworthy value"; the reason is in
        :attr:`state` and must be carried alongside, never dropped.
        """
        return self.value if self.is_present else None

    def as_decimal(self) -> Decimal | None:
        """Return an exact ``Decimal`` for a present number, else ``None``."""
        value = self.as_value()
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int | Decimal):
            return Decimal(value)
        if isinstance(value, str):
            try:
                return Decimal(value)
            except InvalidOperation:
                return None
        return None


@dataclass(frozen=True, slots=True)
class SectionProbe:
    """What was actually found for one section of a decoded report."""

    section: str
    source_path: str
    state: SourceState
    record_count: int | None = None
    records: tuple[object, ...] = field(default_factory=tuple)
    issue: DecodeIssue | None = None


def _walk(document: object, keys: Sequence[str | int]) -> object:
    current: object = document
    for key in keys:
        if isinstance(key, int):
            if not isinstance(current, list) or not -len(current) <= key < len(current):
                return MISSING
            current = current[key]
            continue
        if not isinstance(current, Mapping) or key not in current:
            return MISSING
        current = current[key]
    return current


def probe_field(document: object, *keys: str | int, base_path: str = "") -> FieldProbe:
    """Look up one field and report which of the source states it is in."""
    value = _walk(document, keys)
    state = _state_of(value)
    issue = value.issue if isinstance(value, Invalid) else None
    return FieldProbe(
        source_path=base_path + json_pointer(*keys),
        state=state,
        value=value,
        issue=issue,
    )


def probe_section(document: object, *keys: str | int, base_path: str = "") -> SectionProbe:
    """Look up one section and report its state and how many records it holds.

    An empty object or array is ``present_empty`` with ``record_count = None``:
    an empty aggregate is not a confirmed count of zero.
    """
    value = _walk(document, keys)
    state = _state_of(value)
    section = str(keys[-1]) if keys else ""
    source_path = base_path + json_pointer(*keys)
    if state is SourceState.PRESENT:
        records = tuple(value) if isinstance(value, list) else (value,)
        return SectionProbe(
            section=section,
            source_path=source_path,
            state=state,
            record_count=len(records),
            records=records,
        )
    return SectionProbe(
        section=section,
        source_path=source_path,
        state=state,
        issue=value.issue if isinstance(value, Invalid) else None,
    )
