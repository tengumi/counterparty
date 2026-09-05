"""Digests that pin the import to the exact source it was verified against.

Three different digests answer three different questions:

* :func:`file_digest` — are these the same bytes? It ties a batch to its file.
* :func:`snapshot_digest` — is this the same record? Re-importing an unchanged
  snapshot must be a no-op, and a changed one must become a new version.
* :func:`schema_fingerprint` — is this the same *shape*? Paths and value types
  are hashed without any value, so a source that grows, drops or retypes a
  field is detected before it is silently parsed into the wrong column.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

__all__ = [
    "FINGERPRINT_RULE_VERSION",
    "SchemaFingerprint",
    "canonical_json",
    "file_digest",
    "observed_shape",
    "schema_fingerprint",
    "snapshot_digest",
]

#: Bumped whenever the path or type vocabulary below changes, so a stored
#: fingerprint is never compared against one computed by different rules.
FINGERPRINT_RULE_VERSION: Final = "1"

_CHUNK = 1 << 20


def _type_name(value: object) -> str:
    if isinstance(value, Mapping):
        keys = list(value.keys())
        if len(keys) == 1 and isinstance(keys[0], str) and keys[0].startswith("$"):
            return keys[0]
        return "object"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "int"
    if isinstance(value, Decimal | float):
        return "decimal"
    if isinstance(value, Sequence):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


def _walk(value: object, path: str, shape: dict[str, set[str]]) -> None:
    name = _type_name(value)
    shape.setdefault(path, set()).add(name)
    if name.startswith("$"):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _walk(item, f"{path}/{key}", shape)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            _walk(item, f"{path}/[]", shape)


def observed_shape(records: Iterable[object]) -> dict[str, set[str]]:
    """Map every path template of the source to the value types seen there.

    Array indices collapse to ``[]``: the fingerprint describes the schema, not
    how many records happened to be exported.
    """
    shape: dict[str, set[str]] = {}
    for record in records:
        _walk(record, "", shape)
    return shape


@dataclass(frozen=True, slots=True)
class SchemaFingerprint:
    """A stable digest of the shape of a source file."""

    algorithm: str
    rule_version: str
    digest: str
    path_count: int
    entries: tuple[str, ...]

    def matches(self, expected_digest: str) -> bool:
        """Whether this shape equals a previously approved one."""
        return self.digest == expected_digest


def schema_fingerprint(records: Iterable[object]) -> SchemaFingerprint:
    """Fingerprint the shape of the given records."""
    shape = observed_shape(records)
    entries = tuple(f"{path}\t{','.join(sorted(types))}" for path, types in sorted(shape.items()))
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return SchemaFingerprint(
        algorithm="sha256",
        rule_version=FINGERPRINT_RULE_VERSION,
        digest=digest,
        path_count=len(entries),
        entries=entries,
    )


def file_digest(path: Path) -> str:
    """Return the SHA-256 of the file bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not canonicalizable")


def canonical_json(value: object) -> str:
    """Serialize a record so that equal records produce equal text.

    Keys are sorted because JSONB does not preserve source key order either;
    numbers keep their exact decimal text.
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_default,
    )


def snapshot_digest(record: object) -> str:
    """Return the SHA-256 identifying one snapshot payload.

    Computed on the raw record, before decoding, so the digest depends only on
    the source and not on this parser's version.
    """
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()
