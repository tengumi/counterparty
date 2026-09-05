"""Extended JSON decoding and source fingerprinting for report imports."""

from .approved_source import (
    APPROVED_FILE_NAME,
    APPROVED_FILE_SHA256,
    APPROVED_RECORD_COUNT,
    APPROVED_SCHEMA_FINGERPRINT,
    SUPPORTED_WRAPPERS,
    SourceVerification,
    verify_source,
)
from .extended_json import (
    MISSING,
    Decoded,
    DecodeIssue,
    FieldProbe,
    Invalid,
    IssueCode,
    Missing,
    SectionProbe,
    decode,
    json_pointer,
    load_source_file,
    probe_field,
    probe_section,
)
from .fingerprint import (
    FINGERPRINT_RULE_VERSION,
    SchemaFingerprint,
    canonical_json,
    file_digest,
    observed_shape,
    schema_fingerprint,
    snapshot_digest,
)

__version__ = "0.1.0"

#: Recorded on every import batch so a stored row names the code that wrote it.
PARSER_VERSION = f"import_reports/{__version__}"

__all__ = [
    "APPROVED_FILE_NAME",
    "APPROVED_FILE_SHA256",
    "APPROVED_RECORD_COUNT",
    "APPROVED_SCHEMA_FINGERPRINT",
    "FINGERPRINT_RULE_VERSION",
    "MISSING",
    "PARSER_VERSION",
    "SUPPORTED_WRAPPERS",
    "DecodeIssue",
    "Decoded",
    "FieldProbe",
    "Invalid",
    "IssueCode",
    "Missing",
    "SchemaFingerprint",
    "SectionProbe",
    "SourceVerification",
    "canonical_json",
    "decode",
    "file_digest",
    "json_pointer",
    "load_source_file",
    "observed_shape",
    "probe_field",
    "probe_section",
    "schema_fingerprint",
    "snapshot_digest",
    "verify_source",
]
