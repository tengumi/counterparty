"""The approved mock source and the values it was verified against.

`artifacts/contractors_audit.snapshot.json` is the accepted import source. It is
read in place: this package never writes a cleaned or derived copy of it.

The constants below were measured from that file on 05.09.2026. They are not
decoration — :func:`verify_source` compares them against whatever file is
handed to the importer, so a replaced, truncated or reshaped source is refused
before a single row is written rather than being parsed into the wrong columns.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .fingerprint import FINGERPRINT_RULE_VERSION, file_digest, schema_fingerprint

__all__ = [
    "APPROVED_FILE_NAME",
    "APPROVED_FILE_SHA256",
    "APPROVED_RECORD_COUNT",
    "APPROVED_SCHEMA_FINGERPRINT",
    "APPROVED_SCHEMA_PATH_COUNT",
    "SUPPORTED_WRAPPERS",
    "SourceVerification",
    "verify_source",
]

APPROVED_FILE_NAME: Final = "contractors_audit.snapshot.json"
APPROVED_FILE_SHA256: Final = "34bdf82e3286bfbb1c2b0e4d441dde25c90fd58b1d623d6192f2653dd6641f55"
APPROVED_RECORD_COUNT: Final = 100
APPROVED_SCHEMA_FINGERPRINT: Final = (
    "57e2dfbedb05aa004daa773908155abee5e550a84bdf1d6490f2dc285af5eb3a"
)
APPROVED_SCHEMA_PATH_COUNT: Final = 179

#: Extended JSON wrappers actually present in the approved file. Any other
#: wrapper is reported as an unknown one instead of being guessed at.
SUPPORTED_WRAPPERS: Final = ("$date", "$numberLong")


@dataclass(frozen=True, slots=True)
class SourceVerification:
    """Result of comparing a candidate file with the approved source."""

    path: Path
    file_sha256: str
    record_count: int
    schema_digest: str
    schema_rule_version: str
    schema_path_count: int
    differences: tuple[str, ...]

    @property
    def is_approved_source(self) -> bool:
        """Whether the file is byte-identical to the approved snapshot."""
        return self.file_sha256 == APPROVED_FILE_SHA256

    @property
    def has_approved_shape(self) -> bool:
        """Whether the file has the approved shape, byte-identical or not."""
        return self.schema_digest == APPROVED_SCHEMA_FINGERPRINT


def verify_source(path: Path, records: list[object]) -> SourceVerification:
    """Compare a loaded source file with the approved snapshot."""
    fingerprint = schema_fingerprint(records)
    digest = file_digest(path)
    differences: list[str] = []
    if digest != APPROVED_FILE_SHA256:
        differences.append("file_sha256 differs from the approved snapshot")
    if len(records) != APPROVED_RECORD_COUNT:
        differences.append(
            f"record count {len(records)} differs from the approved {APPROVED_RECORD_COUNT}"
        )
    if fingerprint.digest != APPROVED_SCHEMA_FINGERPRINT:
        differences.append(
            "schema fingerprint differs from the approved shape; review the source before importing"
        )
    return SourceVerification(
        path=path,
        file_sha256=digest,
        record_count=len(records),
        schema_digest=fingerprint.digest,
        schema_rule_version=FINGERPRINT_RULE_VERSION,
        schema_path_count=fingerprint.path_count,
        differences=tuple(differences),
    )
